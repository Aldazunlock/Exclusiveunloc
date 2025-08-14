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
    TOKEN = os.getenv("TELEGRAM_TOKEN", "8295464002:AAE5pmgC_M3MHV1XSh2hCl_nvJ_g9wyMMvY")
    ADMIN_ID = int(os.getenv("ADMIN_ID", "7655366089"))
    CANAL_ID = int(os.getenv("CANAL_ID", "-1002852080157"))
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
                    # Migrar formato antiguo si es necesario
                    if isinstance(data, dict) and 'archivos' not in data:
                        return {
                            'archivos': data,
                            'estadisticas': {'total_busquedas': 0, 'archivos_agregados': len(data)},
                            'version': '1.1'
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
            'version': '1.1'
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
        
        for palabra, enlace in archivos.items():
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

    def es_admin(self, user_id: int) -> bool:
        """Verifica si el usuario es administrador"""
        return user_id == Config.ADMIN_ID

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

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /start"""
        user_info = f"Usuario: {update.effective_user.first_name} (ID: {update.effective_user.id})"
        logger.info(f"Comando /start ejecutado por {user_info}")
        
        keyboard = [
            [InlineKeyboardButton("📚 Ver estadísticas", callback_data="stats")],
            [InlineKeyboardButton("ℹ️ Ayuda", callback_data="help")]
        ]
        
        if self.es_admin(update.effective_user.id):
            keyboard.insert(0, [InlineKeyboardButton("📋 Lista de archivos", callback_data="list")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        mensaje = (
            "🤖 *Bot de Gestión de Archivos v1.2*\n\n"
            "🔍 *Buscar:* `/search <palabra_clave>`\n"
            "📁 *Enviar archivo:* Arrastra y suelta\n"
            f"👥 *Administrador:* {'Sí' if self.es_admin(update.effective_user.id) else 'No'}\n\n"
            "📊 Usa los botones para más opciones"
        )
        
        await update.message.reply_text(
            mensaje,
            parse_mode="Markdown",
            reply_markup=reply_markup
        )

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
        """Comando /list para listar archivos"""
        if not self.es_admin(update.effective_user.id):
            await update.message.reply_text("🚫 No tienes permiso para usar este comando.")
            return

        archivos = self.db['archivos']
        if not archivos:
            await update.message.reply_text("📭 No hay archivos almacenados aún.")
            return

        mensaje = "📚 *Lista de archivos disponibles:*\n\n"
        for i, (clave, info) in enumerate(archivos.items(), 1):
            if isinstance(info, dict):
                fecha = info.get('fecha_agregado', 'Desconocida')[:10]  # Solo la fecha
                mensaje += f"{i}. 📁 `{clave}`\n📅 {fecha}\n"
            else:
                # Compatibilidad con formato antiguo
                mensaje += f"{i}. 📁 `{clave}`\n"
            mensaje += "────────────────────\n"

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
                "• Puedes usar `/list` (solo admin) para ver todos los archivos",
                parse_mode="Markdown"
            )
            return

        mensaje = f"🔍 *Resultados para '{texto}':*\n\n"
        
        for i, (palabra, info, relevancia) in enumerate(resultados, 1):
            if isinstance(info, dict):
                enlace = info['enlace']
                fecha = info.get('fecha_agregado', '')[:10] if info.get('fecha_agregado') else ''
            else:
                enlace = info  # Compatibilidad con formato antiguo
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
                "• `/help` - Ver ayuda\n\n"
                "*Solo administradores:*\n"
                "• `/add <clave> <enlace>` - Agregar archivo\n"
                "• `/delete <clave>` - Eliminar archivo\n"
                "• `/list` - Listar archivos"
            )
            return

        # Para cualquier otro texto, sugerir usar /search
        await update.message.reply_text(
            f"💡 Para buscar '*{texto[:20]}{'...' if len(texto) > 20 else ''}*', usa:\n\n"
            f"`/search {texto}`\n\n"
            "🔍 Esto evita errores y es más claro.",
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
            mensaje = (
                "📊 *Estadísticas del Bot*\n\n"
                f"📁 Total de archivos: *{len(self.db['archivos'])}*\n"
                f"🔍 Total de búsquedas: *{stats.get('total_busquedas', 0)}*\n"
                f"📈 Archivos agregados: *{stats.get('archivos_agregados', 0)}*\n"
                f"📅 Versión: *{self.db.get('version', '1.0')}*"
            )
            await query.edit_message_text(mensaje, parse_mode="Markdown")
            
        elif query.data == "list" and self.es_admin(query.from_user.id):
            # Simular comando list
            await self.list_files(update, context)
            
        elif query.data == "help":
            mensaje = (
                "ℹ️ *Ayuda Rápida*\n\n"
                "*Comandos principales:*\n"
                "• `/search <palabra>` - Buscar archivos\n"
                "• `/help` - Ayuda completa\n"
                "• Envía archivos para guardarlos\n\n"
                f"*Admin:* {'Sí' if self.es_admin(query.from_user.id) else 'No'}\n"
                "Usa `/help` para ver todos los comandos"
            )
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /help"""
        is_admin = self.es_admin(update.effective_user.id)
        
        mensaje = (
            "ℹ️ *Ayuda del Bot de Gestión de Archivos*\n\n"
            "*📋 Comandos disponibles para todos:*\n"
            "• `/start` - Iniciar el bot y ver menú principal\n"
            "• `/search <palabra>` - Buscar archivos por palabra clave\n"
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
                "• `/list` - Ver todos los archivos guardados\n\n"
            )
        
        mensaje += (
            "*💡 Ejemplos de uso:*\n"
            "• `/search honor` - Busca archivos que contengan 'honor'\n"
            "• `/search magic_5` - Búsqueda más específica\n"
        )
        
        if is_admin:
            mensaje += "• `/add mi_app https://ejemplo.com/descarga`\n"
        
        mensaje += "\n🤖 *Versión 1.2* - Bot mejorado con comando search"
        
        await update.message.reply_text(mensaje, parse_mode="Markdown")

def main():
    """Función principal"""
    if not Config.TOKEN:
        logger.error("TOKEN no configurado. Define la variable de entorno TELEGRAM_TOKEN")
        return

    bot = TelegramBot()
    app = ApplicationBuilder().token(Config.TOKEN).build()

    # Registrar handlers
    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CommandHandler("add", bot.add))
    app.add_handler(CommandHandler("delete", bot.delete))
    app.add_handler(CommandHandler("list", bot.list_files))
    app.add_handler(CommandHandler("search", bot.search))
    app.add_handler(CommandHandler("help", bot.help_command))
    app.add_handler(CallbackQueryHandler(bot.button_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, bot.recibir_archivo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_unknown_text))

    logger.info("🤖 Bot iniciado exitosamente...")
    print("🤖 Bot en ejecución...")
    
    try:
        app.run_polling()
    except KeyboardInterrupt:
        logger.info("Bot detenido por el usuario")
    except Exception as e:
        logger.error(f"Error crítico: {e}")

if __name__ == "__main__":
    main()