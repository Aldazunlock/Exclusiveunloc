import json
import os
import logging
import asyncio
import requests
from datetime import datetime
from typing import Dict, Optional, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, 
    ContextTypes, filters, CallbackQueryHandler
)
from telegram.error import TelegramError

# Configuración
class Config:
    DB_FILE = "archivos.json"
    LOG_FILE = "bot.log"
    TOKEN = "7988514338:AAF5_fH0Ud9rjciNPee2kqpmUUDx7--IUj0"
    ADMIN_ID = 7655366089
    CANAL_ID = -1002852080157
    MAX_MESSAGE_LENGTH = 4000
    MAX_SEARCH_RESULTS = 10
    PING_URL = "https://api.telegram.org/bot{}/getMe"
    PING_INTERVAL = 300  # 5 minutos (300 segundos)

# Configuración de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler(Config.LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class DatabaseManager:
    """Manejo de la base de datos JSON"""
    
    @staticmethod
    def cargar_db() -> Dict:
        """Carga la base de datos desde el archivo JSON"""
        try:
            if os.path.exists(Config.DB_FILE):
                with open(Config.DB_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Migrar formato antiguo si es necesario
                    if isinstance(data, dict) and 'archivos' not in data:
                        return {
                            'archivos': data,
                            'estadisticas': {'total_busquedas': 0, 'archivos_agregados': len(data)},
                            'solicitudes': {},
                            'version': '1.2'
                        }
                    return data
        except json.JSONDecodeError as e:
            logger.error(f"Error al cargar DB: {e}")
        except Exception as e:
            logger.error(f"Error inesperado al cargar DB: {e}")
        
        # Retornar estructura por defecto
        return {
            'archivos': {},
            'estadisticas': {'total_busquedas': 0, 'archivos_agregados': 0},
            'solicitudes': {},
            'version': '1.2'
        }

    @staticmethod
    def guardar_db(data: Dict) -> bool:
        """Guarda la base de datos en el archivo JSON"""
        try:
            # Crear backup antes de guardar
            if os.path.exists(Config.DB_FILE):
                backup_name = f"{Config.DB_FILE}.backup"
                os.rename(Config.DB_FILE, backup_name)
            
            with open(Config.DB_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info("Base de datos guardada exitosamente")
            return True
        except Exception as e:
            logger.error(f"Error al guardar DB: {e}")
            return False

    @staticmethod
    def buscar_archivos(query: str, archivos: Dict) -> List[tuple]:
        """Busca archivos que coincidan con la consulta"""
        resultados = []
        query_lower = query.lower().strip()
        
        for palabra, info in archivos.items():
            enlace = info['enlace'] if isinstance(info, dict) else info
            
            # Búsqueda exacta primero
            if query_lower == palabra.lower():
                resultados.insert(0, (palabra, enlace, 100))
            # Búsqueda que contenga la palabra
            elif query_lower in palabra.lower():
                # Calcular relevancia básica
                relevancia = (len(query_lower) / len(palabra)) * 100
                resultados.append((palabra, enlace, relevancia))
        
        # Ordenar por relevancia
        resultados.sort(key=lambda x: x[2], reverse=True)
        return resultados[:Config.MAX_SEARCH_RESULTS]

class TelegramBot:
    def __init__(self):
        self.db_manager = DatabaseManager()
        self.db = self.db_manager.cargar_db()
        self.ping_task = None

    def es_admin(self, user_id: int) -> bool:
        """Verifica si el usuario es administrador"""
        return user_id == Config.ADMIN_ID

    async def auto_ping(self):
        """Función para mantener activo el bot"""
        while True:
            try:
                url = Config.PING_URL.format(Config.TOKEN)
                response = requests.get(url)
                if response.status_code == 200:
                    logger.info("Auto-ping exitoso")
                else:
                    logger.warning(f"Auto-ping falló: {response.status_code}")
            except Exception as e:
                logger.error(f"Error en auto-ping: {e}")
            
            await asyncio.sleep(Config.PING_INTERVAL)

    async def enviar_mensaje_largo(self, update: Update, mensaje: str, parse_mode: str = None):
        """Envía mensajes largos dividiéndolos si es necesario"""
        if len(mensaje) <= Config.MAX_MESSAGE_LENGTH:
            await update.message.reply_text(mensaje, parse_mode=parse_mode)
        else:
            for i in range(0, len(mensaje), Config.MAX_MESSAGE_LENGTH):
                chunk = mensaje[i:i+Config.MAX_MESSAGE_LENGTH]
                await update.message.reply_text(chunk, parse_mode=parse_mode)
                await asyncio.sleep(0.5)  # Evitar rate limiting

    async def publicar_en_canal(self, context: ContextTypes.DEFAULT_TYPE, texto: str = None, documento=None):
        """Publica contenido en el canal configurado"""
        try:
            if documento:
                await context.bot.send_document(
                    chat_id=Config.CANAL_ID, 
                    document=documento,
                    caption=texto
                )
            else:
                await context.bot.send_message(
                    chat_id=Config.CANAL_ID,
                    text=texto
                )
            logger.info("Mensaje enviado al canal exitosamente")
        except TelegramError as e:
            logger.error(f"Error al enviar mensaje al canal: {e}")
            raise

    async def notify_admin(self, context: ContextTypes.DEFAULT_TYPE, message: str):
        """Envía notificación al administrador"""
        try:
            await context.bot.send_message(
                chat_id=Config.ADMIN_ID,
                text=message,
                parse_mode="Markdown"
            )
            return True
        except Exception as e:
            logger.error(f"Error al notificar al admin: {e}")
            return False

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /start"""
        user_info = f"Usuario: {update.effective_user.first_name} (ID: {update.effective_user.id})"
        logger.info(f"Comando /start ejecutado por {user_info}")
        
        keyboard = [
            [InlineKeyboardButton("🔍 Buscar Archivos", callback_data="search_help"),
             InlineKeyboardButton("💵 Solicitar Archivo", callback_data="request_info")],
            [InlineKeyboardButton("📊 Estadísticas", callback_data="stats"),
             InlineKeyboardButton("ℹ️ Ayuda", callback_data="help")]
        ]
        
        if self.es_admin(update.effective_user.id):
            keyboard.insert(0, [InlineKeyboardButton("📋 Lista de Archivos", callback_data="list")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        mensaje = (
            "🤖 *Bot de Gestión de Archivos Premium*\n\n"
            "🔍 *Buscar archivos:* `/search <palabra>`\n"
            "💵 *Solicitar archivo:* `/request <descripción>` (2-3 USD)\n"
            "📁 *Subir archivo:* Arrastra y suelta\n\n"
            "💎 *Servicios premium disponibles*"
        )
        
        await update.message.reply_text(
            mensaje,
            parse_mode="Markdown",
            reply_markup=reply_markup
        )

    async def request_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /request para solicitar archivos"""
        if not context.args:
            await update.message.reply_text(
                "📌 *Solicitud de Archivo*\n\n"
                "🔍 ¿Necesitas un archivo específico?\n\n"
                "💵 *Costo del servicio:* 2-3 USD (dependiendo del archivo)\n\n"
                "📝 *Uso:* `/request <descripción_del_archivo>`\n\n"
                "📋 *Ejemplo:*\n"
                "`/request firmware Honor Magic 5 última versión`",
                parse_mode="Markdown"
            )
            return
        
        descripcion = " ".join(context.args)
        user = update.effective_user
        fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        request_id = f"req_{datetime.now().timestamp()}"
        
        # Guardar solicitud en la base de datos
        self.db['solicitudes'][request_id] = {
            'usuario_id': user.id,
            'usuario_nombre': user.full_name,
            'descripcion': descripcion,
            'fecha': fecha,
            'estado': 'pendiente',
            'precio': None
        }
        self.db_manager.guardar_db(self.db)
        
        # Notificar al administrador
        mensaje_admin = (
            "📬 *Nueva Solicitud de Archivo*\n\n"
            f"🆔 *ID Solicitud:* `{request_id}`\n"
            f"👤 *Usuario:* {user.mention_markdown()}\n"
            f"🆔 *ID:* `{user.id}`\n"
            f"📅 *Fecha:* {fecha}\n\n"
            f"📝 *Descripción:*\n{descripcion}\n\n"
            f"💵 *Precio estimado:* 2-3 USD\n\n"
            "⚠️ *Acciones rápidas:*\n"
            f"- Contactar: /contact {user.id}\n"
            f"- Aprobar solicitud: /approve_request {request_id}\n"
            f"- Rechazar solicitud: /reject_request {request_id}"
        )
        
        try:
            await self.notify_admin(context, mensaje_admin)
            
            # Respuesta al usuario
            await update.message.reply_text(
                "✅ *Solicitud recibida*\n\n"
                "📩 Hemos enviado tu solicitud al administrador.\n"
                "💵 *Costo estimado:* 2-3 USD\n\n"
                "📌 Recibirás una respuesta pronto con los detalles "
                "de disponibilidad y pago.\n\n"
                "🕒 Tiempo estimado de respuesta: 24 horas",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Error al enviar solicitud: {e}")
            await update.message.reply_text(
                "❌ Error al procesar tu solicitud. Por favor intenta más tarde."
            )

    async def approve_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Aprueba una solicitud de archivo"""
        if not self.es_admin(update.effective_user.id):
            await update.message.reply_text("🚫 No tienes permiso para usar este comando.")
            return

        if len(context.args) < 1:
            await update.message.reply_text("⚠️ *Uso:* `/approve_request <request_id> <precio>`", parse_mode="Markdown")
            return

        request_id = context.args[0]
        precio = " ".join(context.args[1:]) if len(context.args) > 1 else "2-3 USD"

        if request_id in self.db['solicitudes']:
            self.db['solicitudes'][request_id]['estado'] = 'aprobado'
            self.db['solicitudes'][request_id]['precio'] = precio
            self.db_manager.guardar_db(self.db)

            # Notificar al usuario
            solicitud = self.db['solicitudes'][request_id]
            try:
                await context.bot.send_message(
                    chat_id=solicitud['usuario_id'],
                    text=(
                        "🎉 *Tu solicitud ha sido aprobada!*\n\n"
                        f"📝 *Descripción:* {solicitud['descripcion']}\n"
                        f"💵 *Precio:* {precio}\n\n"
                        "📌 Por favor contacta al administrador para completar el pago y recibir tu archivo."
                    ),
                    parse_mode="Markdown"
                )
                await update.message.reply_text(f"✅ Solicitud {request_id} aprobada y usuario notificado.")
            except Exception as e:
                await update.message.reply_text(f"✅ Solicitud aprobada pero error al notificar usuario: {e}")
        else:
            await update.message.reply_text(f"❌ No se encontró la solicitud con ID {request_id}")

    async def add(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /add para agregar archivos"""
        if not self.es_admin(update.effective_user.id):
            await update.message.reply_text("🚫 No tienes permiso para usar este comando.")
            return

        if len(context.args) < 2:
            await update.message.reply_text(
                "⚠️ *Uso correcto:*\n"
                "`/add <palabra_clave> <enlace>`\n\n"
                "*Ejemplo:*\n"
                "`/add honor_magic_5 https://ejemplo.com/archivo`",
                parse_mode="Markdown"
            )
            return

        palabra_clave = context.args[0].lower()
        enlace = " ".join(context.args[1:])  # Permitir espacios en URLs

        # Validación básica de URL
        if not (enlace.startswith("http://") or enlace.startswith("https://")):
            await update.message.reply_text("⚠️ El enlace debe comenzar con http:// o https://")
            return

        self.db['archivos'][palabra_clave] = {
            'enlace': enlace,
            'fecha_agregado': datetime.now().isoformat(),
            'agregado_por': update.effective_user.id
        }
        self.db['estadisticas']['archivos_agregados'] += 1
        
        if self.db_manager.guardar_db(self.db):
            await update.message.reply_text(f"✅ Archivo '*{palabra_clave}*' agregado correctamente.", parse_mode="Markdown")
            
            try:
                await self.publicar_en_canal(
                    context,
                    f"📢 *Nuevo archivo agregado*\n📂 `{palabra_clave}`\n🔗 {enlace}",
                )
            except Exception as e:
                await update.message.reply_text(f"⚠️ Archivo agregado, pero error al publicar en canal: {str(e)}")
        else:
            await update.message.reply_text("❌ Error al guardar el archivo. Inténtalo de nuevo.")

    async def delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /delete para eliminar archivos"""
        if not self.es_admin(update.effective_user.id):
            await update.message.reply_text("🚫 No tienes permiso para usar este comando.")
            return

        if len(context.args) != 1:
            await update.message.reply_text("⚠️ *Uso:* `/delete <palabra_clave>`", parse_mode="Markdown")
            return

        palabra_clave = context.args[0].lower()
        
        if palabra_clave in self.db['archivos']:
            del self.db['archivos'][palabra_clave]
            if self.db_manager.guardar_db(self.db):
                await update.message.reply_text(f"✅ Archivo '*{palabra_clave}*' eliminado correctamente.", parse_mode="Markdown")
            else:
                await update.message.reply_text("❌ Error al eliminar el archivo.")
        else:
            await update.message.reply_text(f"❌ No encontré el archivo '*{palabra_clave}*'.", parse_mode="Markdown")

    async def list_files(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /list para listar archivos con diseño mejorado"""
        if not self.es_admin(update.effective_user.id):
            await update.message.reply_text("🚫 No tienes permiso para usar este comando.")
            return

        archivos = self.db['archivos']
        if not archivos:
            await update.message.reply_text("📭 No hay archivos almacenados aún.")
            return

        # Diseño mejorado con emojis y formato
        mensaje = "✨ *📚 Catálogo de Archivos Disponibles* ✨\n\n"
        mensaje += "🔍 *Total de archivos:* " + str(len(archivos)) + "\n"
        mensaje += "📅 *Última actualización:* " + datetime.now().strftime("%Y-%m-%d %H:%M") + "\n\n"
        mensaje += "━━━━━━━━━━━━━━━━━━━━━━\n\n"

        for i, (clave, info) in enumerate(archivos.items(), 1):
            if isinstance(info, dict):
                fecha = info.get('fecha_agregado', 'Desconocida')[:10]
                agregado_por = info.get('agregado_por', '')
                tamaño = f"📏 {info.get('tamaño', 0)/1024/1024:.2f} MB" if info.get('tamaño') else ""
                
                mensaje += f"🔹 *{i}. {clave}*\n"
                mensaje += f"   📅 {fecha} | 👤 {agregado_por}\n"
                if tamaño:
                    mensaje += f"   {tamaño}\n"
                mensaje += "\n"
            else:
                mensaje += f"🔹 *{i}. {clave}*\n\n"

        mensaje += "💡 *Usa* `/search <palabra>` *para buscar archivos*\n"
        mensaje += "💵 *Servicio de solicitud:* `/request <descripción>` (2-3 USD)"

        await self.enviar_mensaje_largo(update, mensaje, "Markdown")

    async def search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /search para buscar archivos"""
        if not context.args:
            await update.message.reply_text(
                "🔍 *Uso del comando de búsqueda:*\n\n"
                "`/search <palabra_clave>`\n\n"
                "*Ejemplos:*\n"
                "• `/search honor`\n"
                "• `/search magic_5`\n"
                "• `/search android`\n\n"
                "💡 *Tip:* Puedes usar palabras parciales",
                parse_mode="Markdown"
            )
            return

        texto = " ".join(context.args)
        logger.info(f"Búsqueda realizada: '{texto}' por usuario {update.effective_user.id}")
        
        # Actualizar estadísticas
        self.db['estadisticas']['total_busquedas'] += 1
        self.db_manager.guardar_db(self.db)
        
        resultados = self.db_manager.buscar_archivos(texto, self.db['archivos'])
        
        if not resultados:
            await update.message.reply_text(
                f"❌ No encontré resultados para '*{texto}*'.\n\n"
                "💡 *Consejos:*\n"
                "• Intenta con palabras más cortas\n"
                "• Revisa la ortografía\n"
                "• Usa palabras clave específicas\n"
                "• Puedes solicitar el archivo con `/request` (2-3 USD)",
                parse_mode="Markdown"
            )
            return

        mensaje = f"🔍 *Resultados para '{texto}':*\n\n"
        
        for i, (palabra, enlace, relevancia) in enumerate(resultados, 1):
            info = self.db['archivos'].get(palabra, {})
            
            if isinstance(info, dict):
                fecha = info.get('fecha_agregado', '')[:10] if info.get('fecha_agregado') else ''
            else:
                fecha = ''
            
            mensaje += f"*{i}. 📁 {palabra}*\n"
            
            if enlace.startswith("file_id:"):
                mensaje += "📎 Archivo guardado en Telegram\n"
                mensaje += "👤 Contacta al administrador para obtenerlo\n"
            else:
                mensaje += f"🔗 {enlace}\n"
            
            if fecha:
                mensaje += f"📅 Agregado: {fecha}\n"
            mensaje += f"📊 Relevancia: {relevancia:.1f}%\n"
            mensaje += "────────────────────\n"

        mensaje += "\n💵 ¿No encuentras lo que buscas? Usa `/request` para solicitarlo (2-3 USD)"
        
        await self.enviar_mensaje_largo(update, mensaje, "Markdown")

    async def handle_unknown_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Maneja texto que no es comando"""
        texto = update.message.text.strip()
        
        # Ignorar si parece ser un comando mal escrito
        if texto.startswith('/'):
            await update.message.reply_text(
                "❓ Comando no reconocido.\n\n"
                "*Comandos disponibles:*\n"
                "• `/start` - Iniciar bot\n"
                "• `/search <palabra>` - Buscar archivos\n"
                "• `/request <descripción>` - Solicitar archivo (2-3 USD)\n"
                "• `/help` - Ver ayuda\n\n"
                "*Solo administradores:*\n"
                "• `/add <clave> <enlace>` - Agregar archivo\n"
                "• `/delete <clave>` - Eliminar archivo\n"
                "• `/list` - Listar archivos"
            )
            return

        # Para cualquier otro texto, sugerir usar /search o /request
        await update.message.reply_text(
            f"💡 ¿Quieres buscar '*{texto[:20]}{'...' if len(texto) > 20 else ''}*'?\n\n"
            f"🔍 Usa `/search {texto}` para buscar en nuestros archivos\n"
            f"💵 O `/request {texto}` para solicitarlo (2-3 USD)",
            parse_mode="Markdown"
        )

    async def recibir_archivo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Procesar archivos enviados"""
        documento = update.message.document
        if not documento:
            return

        user_info = f"{update.effective_user.first_name} (ID: {update.effective_user.id})"
        logger.info(f"Archivo recibido: {documento.file_name} de {user_info}")

        nombre_archivo = documento.file_name or "archivo_sin_nombre"
        file_id = documento.file_id
        
        # Generar clave única
        clave = nombre_archivo.lower().replace(" ", "_").replace(".", "_")
        contador = 1
        clave_original = clave
        
        while clave in self.db['archivos']:
            clave = f"{clave_original}_{contador}"
            contador += 1

        self.db['archivos'][clave] = {
            'enlace': f"file_id:{file_id}",
            'fecha_agregado': datetime.now().isoformat(),
            'agregado_por': update.effective_user.id,
            'nombre_original': nombre_archivo,
            'tamaño': documento.file_size
        }
        self.db['estadisticas']['archivos_agregados'] += 1

        if self.db_manager.guardar_db(self.db):
            await update.message.reply_text(
                f"✅ Archivo '*{nombre_archivo}*' guardado con clave '*{clave}*'\n"
                f"📊 Tamaño: {documento.file_size / 1024 / 1024:.2f} MB",
                parse_mode="Markdown"
            )

            try:
                await self.publicar_en_canal(
                    context,
                    f"📂 *Nuevo archivo:* {nombre_archivo}\n🔑 *Clave:* `{clave}`",
                    file_id
                )
            except Exception as e:
                await update.message.reply_text(f"⚠️ Archivo guardado, pero error al publicar: {str(e)}")
        else:
            await update.message.reply_text("❌ Error al guardar el archivo.")

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Maneja los botones inline"""
        query = update.callback_query
        await query.answer()

        if query.data == "stats":
            stats = self.db['estadisticas']
            solicitudes_pendientes = len([r for r in self.db['solicitudes'].values() if r.get('estado') == 'pendiente'])
            
            mensaje = (
                "📊 *Estadísticas del Bot*\n\n"
                f"📁 Total de archivos: *{len(self.db['archivos'])}*\n"
                f"🔍 Total de búsquedas: *{stats.get('total_busquedas', 0)}*\n"
                f"📈 Archivos agregados: *{stats.get('archivos_agregados', 0)}*\n"
                f"📬 Solicitudes pendientes: *{solicitudes_pendientes}*\n"
                f"📅 Versión: *{self.db.get('version', '1.2')}*"
            )
            await query.edit_message_text(mensaje, parse_mode="Markdown")
            
        elif query.data == "list" and self.es_admin(query.from_user.id):
            # Simular comando list
            await self.list_files(update, context)
            
        elif query.data == "help":
            await self.help_command(update, context)
            
        elif query.data == "search_help":
            await query.edit_message_text(
                "🔍 *Ayuda de Búsqueda*\n\n"
                "Para buscar archivos, usa:\n"
                "`/search <palabra_clave>`\n\n"
                "*Ejemplos:*\n"
                "• `/search honor`\n"
                "• `/search magic_5`\n"
                "• `/search android`\n\n"
                "💡 *Tips:*\n"
                "- Usa palabras clave específicas\n"
                "- Puedes buscar por partes del nombre\n"
                "- Si no encuentras, usa `/request` para solicitarlo (2-3 USD)",
                parse_mode="Markdown"
            )
            
        elif query.data == "request_info":
            await query.edit_message_text(
                "💵 *Solicitud de Archivos*\n\n"
                "¿No encuentras lo que buscas? ¡Podemos conseguirlo por ti!\n\n"
                "📝 *Cómo solicitar:*\n"
                "`/request <descripción_del_archivo>`\n\n"
                "*Ejemplo:*\n"
                "`/request firmware Honor Magic 5 última versión`\n\n"
                "💲 *Costo del servicio:* 2-3 USD\n"
                "⏱ *Tiempo de respuesta:* 24 horas\n\n"
                "📌 El administrador te contactará con los detalles de pago y disponibilidad.",
                parse_mode="Markdown"
            )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /help"""
        is_admin = self.es_admin(update.effective_user.id)
        
        mensaje = (
            "ℹ️ *Ayuda del Bot de Gestión de Archivos*\n\n"
            "*📋 Comandos disponibles para todos:*\n"
            "• `/start` - Iniciar el bot y ver menú principal\n"
            "• `/search <palabra>` - Buscar archivos por palabra clave\n"
            "• `/request <descripción>` - Solicitar archivo (2-3 USD)\n"
            "• `/help` - Mostrar esta ayuda\n\n"
            "*📁 Envío de archivos:*\n"
            "• Arrastra y suelta cualquier archivo\n"
            "• Se guardará automáticamente con una clave única\n"
            "• Se publicará en el canal configurado\n\n"
        )
        
        if is_admin:
            mensaje += (
                "*🔧 Comandos de administrador:*\n"
                "• `/add <clave> <enlace>` - Agregar archivo manualmente\n"
                "• `/delete <clave>` - Eliminar un archivo\n"
                "• `/list` - Ver todos los archivos guardados\n"
                "• `/approve_request <id>` - Aprobar solicitud\n\n"
            )
        
        mensaje += (
            "*💡 Ejemplos de uso:*\n"
            "• `/search honor` - Busca archivos que contengan 'honor'\n"
            "• `/request firmware_xiaomi` - Solicita un firmware\n"
        )
        
        if is_admin:
            mensaje += "• `/add mi_app https://ejemplo.com/descarga`\n"
        
        mensaje += "\n🤖 *Versión 1.2* - Bot mejorado con sistema de solicitudes premium"
        
        if isinstance(update, Update):
            await update.message.reply_text(mensaje, parse_mode="Markdown")
        else:
            await update.callback_query.edit_message_text(mensaje, parse_mode="Markdown")

def main():
    """Función principal"""
    bot = TelegramBot()
    app = ApplicationBuilder().token(Config.TOKEN).build()

    # Registrar handlers
    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CommandHandler("add", bot.add))
    app.add_handler(CommandHandler("delete", bot.delete))
    app.add_handler(CommandHandler("list", bot.list_files))
    app.add_handler(CommandHandler("search", bot.search))
    app.add_handler(CommandHandler("request", bot.request_file))
    app.add_handler(CommandHandler("approve_request", bot.approve_request))
    app.add_handler(CommandHandler("help", bot.help_command))
    app.add_handler(CallbackQueryHandler(bot.button_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, bot.recibir_archivo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_unknown_text))

    # Configurar auto-ping
    bot.ping_task = asyncio.create_task(bot.auto_ping())

    logger.info("🤖 Bot iniciado exitosamente...")
    print("🤖 Bot en ejecución...")
    
    try:
        app.run_polling()
    except KeyboardInterrupt:
        logger.info("Bot detenido por el usuario")
    except Exception as e:
        logger.error(f"Error inesperado: {e}")
    finally:
        if bot.ping_task:
            bot.ping_task.cancel()

if __name__ == "__main__":
    main()