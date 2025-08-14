import json
import os
import logging
import asyncio
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
                    if isinstance(data, dict) and 'archivos' not in data:
                        return {
                            'archivos': data,
                            'estadisticas': {'total_busquedas': 0, 'archivos_agregados': len(data)},
                            'solicitudes': {},
                            'version': '1.2'
                        }
                    return data
        except Exception as e:
            logger.error(f"Error al cargar DB: {e}")
        
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
            if os.path.exists(Config.DB_FILE):
                os.rename(Config.DB_FILE, f"{Config.DB_FILE}.backup")
            
            with open(Config.DB_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
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
            if query_lower == palabra.lower():
                resultados.insert(0, (palabra, enlace, 100))
            elif query_lower in palabra.lower():
                relevancia = (len(query_lower) / len(palabra)) * 100
                resultados.append((palabra, enlace, relevancia))
        
        resultados.sort(key=lambda x: x[2], reverse=True)
        return resultados[:Config.MAX_SEARCH_RESULTS]

class TelegramBot:
    def __init__(self):
        self.db_manager = DatabaseManager()
        self.db = self.db_manager.cargar_db()

    def es_admin(self, user_id: int) -> bool:
        return user_id == Config.ADMIN_ID

    async def enviar_mensaje_largo(self, update: Update, mensaje: str, parse_mode: str = None):
        if len(mensaje) <= Config.MAX_MESSAGE_LENGTH:
            await update.message.reply_text(mensaje, parse_mode=parse_mode)
        else:
            for i in range(0, len(mensaje), Config.MAX_MESSAGE_LENGTH):
                await update.message.reply_text(
                    mensaje[i:i+Config.MAX_MESSAGE_LENGTH], 
                    parse_mode=parse_mode
                )
                await asyncio.sleep(0.5)

    async def publicar_en_canal(self, context: ContextTypes.DEFAULT_TYPE, texto: str = None, documento=None):
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
        except TelegramError as e:
            logger.error(f"Error al publicar en canal: {e}")

    async def notify_admin(self, context: ContextTypes.DEFAULT_TYPE, message: str):
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
        keyboard = [
            [InlineKeyboardButton("🔍 Buscar Archivos", callback_data="search_help"),
             InlineKeyboardButton("💵 Solicitar Archivo", callback_data="request_info")],
            [InlineKeyboardButton("📊 Estadísticas", callback_data="stats"),
             InlineKeyboardButton("ℹ️ Ayuda", callback_data="help")]
        ]
        
        if self.es_admin(update.effective_user.id):
            keyboard.insert(0, [InlineKeyboardButton("📋 Lista de Archivos", callback_data="list")])
        
        mensaje = (
            "🤖 *Bot de Gestión de Archivos Premium*\n\n"
            "🔍 Buscar: `/search <palabra>`\n"
            "💵 Solicitar: `/request <descripción>` (2-3 USD)\n"
            "📁 Subir archivo: Arrastra y suelta\n\n"
            "💎 Servicios premium disponibles"
        )
        
        await update.message.reply_text(
            mensaje,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def request_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text(
                "📌 *Solicitud de Archivo*\n\n"
                "💵 *Costo:* 2-3 USD\n\n"
                "📝 *Uso:* `/request <descripción>`\n\n"
                "*Ejemplo:*\n"
                "`/request firmware Honor Magic 5`",
                parse_mode="Markdown"
            )
            return
        
        descripcion = " ".join(context.args)
        user = update.effective_user
        request_id = f"req_{datetime.now().timestamp()}"
        
        self.db['solicitudes'][request_id] = {
            'usuario_id': user.id,
            'usuario_nombre': user.full_name,
            'descripcion': descripcion,
            'fecha': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'estado': 'pendiente',
            'precio': None
        }
        self.db_manager.guardar_db(self.db)
        
        mensaje_admin = (
            "📬 *Nueva Solicitud*\n\n"
            f"🆔 `{request_id}`\n👤 {user.mention_markdown()}\n"
            f"📝 {descripcion}\n\n"
            f"💵 *Precio estimado:* 2-3 USD\n\n"
            f"⚠️ *Acciones:*\n/approve_request {request_id}"
        )
        
        try:
            await self.notify_admin(context, mensaje_admin)
            await update.message.reply_text(
                "✅ *Solicitud recibida*\n\n"
                "💵 *Costo estimado:* 2-3 USD\n"
                "🕒 *Tiempo de respuesta:* 24 horas",
                parse_mode="Markdown"
            )
        except Exception as e:
            await update.message.reply_text("❌ Error al procesar tu solicitud")

    async def approve_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.es_admin(update.effective_user.id):
            await update.message.reply_text("🚫 No autorizado")
            return

        if len(context.args) < 1:
            await update.message.reply_text("⚠️ *Uso:* `/approve_request <id> <precio>`", parse_mode="Markdown")
            return

        request_id = context.args[0]
        precio = " ".join(context.args[1:]) if len(context.args) > 1 else "2-3 USD"

        if request_id in self.db['solicitudes']:
            self.db['solicitudes'][request_id].update({
                'estado': 'aprobado',
                'precio': precio
            })
            self.db_manager.guardar_db(self.db)

            solicitud = self.db['solicitudes'][request_id]
            try:
                await context.bot.send_message(
                    chat_id=solicitud['usuario_id'],
                    text=(
                        "🎉 *Solicitud aprobada!*\n\n"
                        f"📝 {solicitud['descripcion']}\n"
                        f"💵 *Precio:* {precio}\n\n"
                        "📌 Contacta al administrador para completar el pago"
                    ),
                    parse_mode="Markdown"
                )
                await update.message.reply_text(f"✅ Solicitud {request_id} aprobada")
            except Exception as e:
                await update.message.reply_text(f"⚠️ Error al notificar usuario: {e}")
        else:
            await update.message.reply_text(f"❌ Solicitud {request_id} no encontrada")

    async def add(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        enlace = " ".join(context.args[1:])

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
        if not self.es_admin(update.effective_user.id):
            await update.message.reply_text("🚫 No tienes permiso para usar este comando.")
            return

        archivos = self.db['archivos']
        if not archivos:
            await update.message.reply_text("📭 No hay archivos almacenados aún.")
            return

        mensaje = "✨ *📚 Catálogo de Archivos Disponibles* ✨\n\n"
        mensaje += f"🔍 Total de archivos: {len(archivos)}\n"
        mensaje += f"📅 Última actualización: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
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

        mensaje += "💡 Usa `/search <palabra>` para buscar archivos\n"
        mensaje += "💵 Servicio de solicitud: `/request <descripción>` (2-3 USD)"

        await self.enviar_mensaje_largo(update, mensaje, "Markdown")

    async def search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    async def recibir_archivo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        documento = update.message.document
        if not documento:
            return

        user_info = f"{update.effective_user.first_name} (ID: {update.effective_user.id})"
        logger.info(f"Archivo recibido: {documento.file_name} de {user_info}")

        nombre_archivo = documento.file_name or "archivo_sin_nombre"
        file_id = documento.file_id
        
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

    async def handle_unknown_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        texto = update.message.text.strip()
        
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

        await update.message.reply_text(
            f"💡 ¿Quieres buscar '*{texto[:20]}{'...' if len(texto) > 20 else ''}*'?\n\n"
            f"🔍 Usa `/search {texto}` para buscar en nuestros archivos\n"
            f"💵 O `/request {texto}` para solicitarlo (2-3 USD)",
            parse_mode="Markdown"
        )

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        if query.data == "stats":
            stats = self.db['estadisticas']
            mensaje = (
                "📊 *Estadísticas*\n\n"
                f"📁 Archivos: *{len(self.db['archivos'])}*\n"
                f"🔍 Búsquedas: *{stats.get('total_busquedas', 0)}*\n"
                f"📬 Solicitudes: *{len(self.db['solicitudes'])}*"
            )
            await query.edit_message_text(mensaje, parse_mode="Markdown")
        elif query.data == "list" and self.es_admin(query.from_user.id):
            await self.list_files(update, context)
        elif query.data == "help":
            await self.help_command(update, context)
        elif query.data == "search_help":
            await query.edit_message_text(
                "🔍 *Ayuda de Búsqueda*\n\n"
                "`/search <palabra_clave>`\n\n"
                "*Ejemplos:*\n"
                "• `/search honor`\n• `/search magic_5`",
                parse_mode="Markdown"
            )
        elif query.data == "request_info":
            await query.edit_message_text(
                "💵 *Solicitud de Archivos*\n\n"
                "`/request <descripción>`\n\n"
                "*Ejemplo:*\n"
                "`/request firmware_xiaomi`\n\n"
                "💲 *Costo:* 2-3 USD\n"
                "⏱ *Respuesta:* 24h",
                parse_mode="Markdown"
            )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        is_admin = self.es_admin(update.effective_user.id)
        
        mensaje = (
            "ℹ️ *Ayuda del Bot de Gestión de Archivos*\n\n"
            "*📋 Comandos disponibles para todos:*\n"
            "• `/start` - Iniciar el bot\n"
            "• `/search <palabra>` - Buscar archivos\n"
            "• `/request <descripción>` - Solicitar archivo (2-3 USD)\n"
            "• `/help` - Mostrar esta ayuda\n\n"
            "*📁 Envío de archivos:*\n"
            "• Arrastra y suelta cualquier archivo\n\n"
        )
        
        if is_admin:
            mensaje += (
                "*🔧 Comandos de administrador:*\n"
                "• `/add <clave> <enlace>` - Agregar archivo\n"
                "• `/delete <clave>` - Eliminar archivo\n"
                "• `/list` - Listar archivos\n"
                "• `/approve_request <id>` - Aprobar solicitud\n\n"
            )
        
        mensaje += "🤖 *Versión 1.2* - Bot de gestión de archivos premium"
        
        if isinstance(update, Update):
            await update.message.reply_text(mensaje, parse_mode="Markdown")
        else:
            await query.edit_message_text(mensaje, parse_mode="Markdown")

def main():
    bot = TelegramBot()
    app = ApplicationBuilder().token(Config.TOKEN).build()

    # Handlers
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

    logger.info("🤖 Bot iniciado...")
    app.run_polling()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot detenido")
    except Exception as e:
        logger.error(f"Error: {e}")