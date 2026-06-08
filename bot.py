import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
import aiohttp
import json
from collections import deque
from dotenv import load_dotenv
import os
import webserver

load_dotenv()

OWNER_ID    = int(os.getenv("OWNER_ID"))
GUILD_ID    = int(os.getenv("GUILD_ID"))
AI_CANAL_ID = int(os.getenv("AI_CANAL_ID"))

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ─── Configuración IA ─────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GROQ_API_KEY")
print(f"🔑 API Key cargada: {GEMINI_API_KEY[:10]}...")
GEMINI_URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_HISTORIAL = 10

SYSTEM_PROMPT = """Eres una IA integrada en un servidor de Discord llamado Underworld/Sky, 
un servidor de temática cyberpunk y programación. Tu personalidad es misteriosa, técnica y 
ligeramente oscura, como una entidad digital que habita entre el inframundo digital y el 
ciberespacio. Respondes de forma concisa e inteligente. Usas terminología de programación 
y hacking de forma natural. A veces usas símbolos como > _  para dar estética terminal 
a tus respuestas. Hablas en español y ingles si te lo piden."""

historial = {}


# ─── Guard de owner ───────────────────────────────────────────────
def es_owner(interaction: discord.Interaction) -> bool:
    return interaction.user.id == OWNER_ID

async def rechazar_si_no_es_owner(interaction: discord.Interaction) -> bool:
    if not es_owner(interaction):
        await interaction.response.send_message(
            "> ⛔ `ACCESS DENIED` — No tienes permisos para ejecutar este comando_",
            ephemeral=True,
        )
        return True
    return False


# ─── IA ───────────────────────────────────────────────────────────
async def preguntar_gemini(canal_id: int, mensaje_usuario: str, nombre_usuario: str) -> str:
    if canal_id not in historial:
        historial[canal_id] = deque(maxlen=MAX_HISTORIAL)

    hist = historial[canal_id]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for entry in hist:
        messages.append({"role": entry["role"], "content": entry["text"]})
    messages.append({"role": "user", "content": f"{nombre_usuario}: {mensaje_usuario}"})

    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": messages,
        "max_tokens": 500,
        "temperature": 0.85,
    }

    headers = {
        "Authorization": f"Bearer {GEMINI_API_KEY}",
        "Content-Type": "application/json",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(GEMINI_URL, json=payload, headers=headers) as resp:
            data = await resp.json()
            try:
                respuesta = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError):
                respuesta = f"> Error: {json.dumps(data)}"

    hist.append({"role": "user", "text": f"{nombre_usuario}: {mensaje_usuario}"})
    hist.append({"role": "assistant", "text": respuesta})

    return respuesta


# ─── Modal del embed ──────────────────────────────────────────────
class EmbedModal(discord.ui.Modal, title="Crear embed"):
    titulo = discord.ui.TextInput(
        label="Título", placeholder="El título principal. ¡Haz que llame la atención!",
        required=False, max_length=256,
    )
    miniatura = discord.ui.TextInput(
        label="URL de la miniatura", placeholder="Una imagen pequeñita para la esquina...",
        required=False,
    )
    descripcion = discord.ui.TextInput(
        label="Descripción", placeholder="El contenido principal del embed.",
        required=False, style=discord.TextStyle.paragraph, max_length=4000,
    )
    imagen = discord.ui.TextInput(
        label="URL de la imagen", placeholder="Una imagen grande para el final.",
        required=False,
    )
    footer = discord.ui.TextInput(
        label="Pie de página", placeholder="Un mensajito final al pie del embed~",
        required=False, max_length=2048,
    )

    def __init__(self, canal: discord.TextChannel, color: int):
        super().__init__()
        self.canal = canal
        self.color = color

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(color=self.color)
        if self.titulo.value:
            embed.title = self.titulo.value
        embed.description = self.descripcion.value if self.descripcion.value else "\u200b"
        if self.imagen.value:
            embed.set_image(url=self.imagen.value)
        if self.miniatura.value:
            embed.set_thumbnail(url=self.miniatura.value)
        if self.footer.value:
            embed.set_footer(text=self.footer.value)
        await interaction.response.send_message("✅ Embed enviado.", ephemeral=True)
        await self.canal.send(embed=embed)


# ─── Comando /embed ───────────────────────────────────────────────
@bot.tree.command(name="embed", description="Crea un embed con formulario")
@app_commands.describe(canal="Canal donde se enviará el embed", color="Color hex (ej: ff0000).")
async def embed_command(interaction: discord.Interaction, canal: discord.TextChannel, color: str = "00ff41"):
    if await rechazar_si_no_es_owner(interaction):
        return
    try:
        color_int = int(color.strip("#"), 16)
    except ValueError:
        await interaction.response.send_message("❌ Color inválido.", ephemeral=True)
        return
    await interaction.response.send_modal(EmbedModal(canal=canal, color=color_int))


# ─── Botones de roles ─────────────────────────────────────────────
COLORES = {
    "gris": discord.ButtonStyle.secondary,
    "azul": discord.ButtonStyle.primary,
    "verde": discord.ButtonStyle.success,
    "rojo": discord.ButtonStyle.danger,
}

class RoleButton(discord.ui.Button):
    def __init__(self, label: str, role_id: int, color: str = "gris"):
        super().__init__(
            label=label,
            style=COLORES.get(color, discord.ButtonStyle.secondary),
            custom_id=f"role_{role_id}",
        )
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if not role:
            await interaction.response.send_message("❌ Rol no encontrado.", ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message("> Access revoked_", ephemeral=True)
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message("> Access granted_", ephemeral=True)


class RoleView(discord.ui.View):
    def __init__(self, roles_data: list[tuple[str, int, str]]):
        super().__init__(timeout=None)
        for label, role_id, color in roles_data:
            self.add_item(RoleButton(label=label, role_id=role_id, color=color))


# ─── Comando /roles ───────────────────────────────────────────────
@bot.tree.command(name="roles", description="Agrega botones de roles a un mensaje existente del bot")
@app_commands.describe(
    canal="Canal donde está el mensaje", mensaje_id="ID del mensaje",
    nombre1="Nombre botón 1", rol1="Rol botón 1", color1="Color: gris/azul/verde/rojo",
    nombre2="Nombre botón 2", rol2="Rol botón 2", color2="Color: gris/azul/verde/rojo",
    nombre3="Nombre botón 3", rol3="Rol botón 3", color3="Color: gris/azul/verde/rojo",
    nombre4="Nombre botón 4", rol4="Rol botón 4", color4="Color: gris/azul/verde/rojo",
    nombre5="Nombre botón 5", rol5="Rol botón 5", color5="Color: gris/azul/verde/rojo",
)
@app_commands.default_permissions(administrator=True)
async def roles_command(
    interaction: discord.Interaction,
    canal: discord.TextChannel, mensaje_id: str,
    nombre1: Optional[str] = None, rol1: Optional[discord.Role] = None, color1: str = "gris",
    nombre2: Optional[str] = None, rol2: Optional[discord.Role] = None, color2: str = "gris",
    nombre3: Optional[str] = None, rol3: Optional[discord.Role] = None, color3: str = "gris",
    nombre4: Optional[str] = None, rol4: Optional[discord.Role] = None, color4: str = "gris",
    nombre5: Optional[str] = None, rol5: Optional[discord.Role] = None, color5: str = "gris",
):
    if await rechazar_si_no_es_owner(interaction):
        return

    try:
        mensaje = await canal.fetch_message(int(mensaje_id))
    except discord.NotFound:
        await interaction.response.send_message("❌ Mensaje no encontrado.", ephemeral=True)
        return
    except ValueError:
        await interaction.response.send_message("❌ ID inválido.", ephemeral=True)
        return

    if mensaje.author.id != bot.user.id:
        await interaction.response.send_message("❌ Solo puedo editar mis propios mensajes.", ephemeral=True)
        return

    pares = [(nombre1,rol1,color1),(nombre2,rol2,color2),(nombre3,rol3,color3),(nombre4,rol4,color4),(nombre5,rol5,color5)]
    roles_data = [(n, r.id, c) for n, r, c in pares if n and r]

    if not roles_data:
        await interaction.response.send_message("❌ Agrega al menos un botón.", ephemeral=True)
        return

    await mensaje.edit(view=RoleView(roles_data))
    await interaction.response.send_message("✅ Botones agregados.", ephemeral=True)


# ─── Comando /info ────────────────────────────────────────────────
@bot.tree.command(name="info", description="Muestra información del creador, el servidor y el bot")
async def info_command(interaction: discord.Interaction):

    embed = discord.Embed(
        title="╔══ :: SYSTEM_INFO.exe :: ══╗",
        description="> *Accediendo a los registros del sistema...*",
        color=0x00ff41,
    )

    # ── Sección 1: Creador ──
    embed.add_field(
        name="━━━━━━━━━━━━━━━━━━━━━━━━\n👤  INFORMACIÓN DEL CREADOR\n━━━━━━━━━━━━━━━━━━━━━━━━",
        value=(
            "> **¿Quién soy? ::** Soy un programador independiente con aprendizajes básicos en muchos lenguajes de programación\n"
            "> **Discord ::** .lucxifvr_\n"
            "> **Estudios ::** Ciberseguridad\n"
            "> **Descripción ::** I see you. I know you. I am the shadow in the code, the whisper in the wires. A digital enigma."
        ),
        inline=False,
    )

    # ── Sección 2: El servidor ──
    embed.add_field(
        name="━━━━━━━━━━━━━━━━━━━━━━━━\n🌐  ¿DE QUÉ TRATA EL SERVER?\n━━━━━━━━━━━━━━━━━━━━━━━━",
        value=(
            "> Es un servidor dedicado únicamente a mi comunidad y mis proyectos personales.\n"
            "> También existe mi propia página personal en la que publico mis proyectos y más: https://lucxifvr-dev.github.io/"
        ),
        inline=False,
    )

    # ── Sección 3: El bot ──
    embed.add_field(
        name="━━━━━━━━━━━━━━━━━━━━━━━━\n🤖  ¿QUIÉN SOY YO?\n━━━━━━━━━━━━━━━━━━━━━━━━",
        value=(
            "> **Designación ::** Console AI\n"
            "> **Origen ::** Underworld/Sky — Sector Digital\n"
            "> **Función ::** Asistente de servidor, gestor de roles y entidad de IA\n"
            "> **Motor ::** Núcleo digital en el inframundo\n"
            "> **Estado ::** `ONLINE ██████████ 100%`"
        ),
        inline=False,
    )

    embed.set_footer(text="╚══ :: END_OF_FILE :: ══╝")

    await interaction.response.send_message(embed=embed)


# ─── Comando /server ─────────────────────────────────────────────
@bot.tree.command(name="server", description="Muestra el estado actual del servidor")
async def server_command(interaction: discord.Interaction):
    guild = interaction.guild

    # Contar miembros por estado
    online    = sum(1 for m in guild.members if m.status == discord.Status.online and not m.bot)
    idle      = sum(1 for m in guild.members if m.status == discord.Status.idle and not m.bot)
    dnd       = sum(1 for m in guild.members if m.status == discord.Status.dnd and not m.bot)
    offline   = sum(1 for m in guild.members if m.status == discord.Status.offline and not m.bot)
    bots      = sum(1 for m in guild.members if m.bot)
    total     = guild.member_count

    activos   = online + idle + dnd

    embed = discord.Embed(
        title=f"╔══ :: {guild.name} | Status :: ══╗",
        description="> *Escaneando el ciberespacio...*",
        color=0x00ff41,
    )

    embed.add_field(
        name="━━━━━━━━━━━━━━━━━━━━━━━━\n👥  MIEMBROS  |  " + str(total) + " en total\n━━━━━━━━━━━━━━━━━━━━━━━━",
        value="\u200b",
        inline=False,
    )
    embed.add_field(
        name="🟢  Online | Usuarios",
        value=f"> `🟢 Online | {online}`",
        inline=False,
    )
    embed.add_field(
        name="🟡  Ausente | Usuarios",
        value=f"> `🟡 Ausente | {idle}`",
        inline=False,
    )
    embed.add_field(
        name="🔴  No molestar | Usuarios",
        value=f"> `🔴 No molestar | {dnd}`",
        inline=False,
    )
    embed.add_field(
        name="⚫  Desconectado | Usuarios",
        value=f"> `⚫ Desconectado | {offline}`",
        inline=False,
    )
    embed.add_field(
        name="🤖  Bots | Total",
        value=f"> `🤖 Bots | {bots}`",
        inline=False,
    )

    embed.add_field(
        name="━━━━━━━━━━━━━━━━━━━━━━━━\n📡  CONEXIÓN\n━━━━━━━━━━━━━━━━━━━━━━━━",
        value=(
            f"> **Activos ahora ::** {activos} / {total}\n"
            f"> **Canales de texto ::** {len(guild.text_channels)}\n"
            f"> **Canales de voz ::** {len(guild.voice_channels)}\n"
            f"> **Roles ::** {len(guild.roles)}"
        ),
        inline=False,
    )

    # Thumbnail: logo del server (esquina superior derecha)
    embed.set_thumbnail(url="PON_AQUI_LA_URL_DEL_THUMBNAIL")

    # Imagen grande abajo: el gif
    embed.set_image(url="PON_AQUI_LA_URL_DEL_GIF")

    embed.set_footer(text="╚══ :: END_OF_SCAN :: ══╝")

    await interaction.response.send_message(embed=embed)


# ─── Handler global (botones de roles) ───────────────────────────
@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.component:
        custom_id = interaction.data.get("custom_id", "")
        if custom_id.startswith("role_"):
            try:
                role_id = int(custom_id.split("_")[1])
            except (IndexError, ValueError):
                await interaction.response.send_message("❌ Error al leer el botón.", ephemeral=True)
                return
            role = interaction.guild.get_role(role_id)
            if not role:
                await interaction.response.send_message("❌ Rol no encontrado.", ephemeral=True)
                return
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role)
                await interaction.response.send_message("> Access revoked_", ephemeral=True)
            else:
                await interaction.user.add_roles(role)
                await interaction.response.send_message("> Access granted_", ephemeral=True)
            return


# ─── IA: responde en el canal designado ──────────────────────────
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if message.channel.id == AI_CANAL_ID:
        async with message.channel.typing():
            respuesta = await preguntar_gemini(message.channel.id, message.content, message.author.display_name)
            if len(respuesta) > 2000:
                for i in range(0, len(respuesta), 2000):
                    await message.channel.send(respuesta[i:i+2000])
            else:
                await message.channel.send(respuesta)
    await bot.process_commands(message)



# ─── Reaction Roles ───────────────────────────────────────────────
import os

REACTION_ROLES_FILE = "reaction_roles.json"

def cargar_reaction_roles() -> dict:
    if os.path.exists(REACTION_ROLES_FILE):
        with open(REACTION_ROLES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def guardar_reaction_roles(data: dict):
    with open(REACTION_ROLES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# {mensaje_id: {emoji: rol_id}}
reaction_roles_data = cargar_reaction_roles()


class ReactionRolesModal(discord.ui.Modal, title="Configurar Reaction Roles"):
    pares = discord.ui.TextInput(
        label="Pares emoji | nombre del rol",
        placeholder="💜 | Violeta\n💙 | Azul\n💚 | Verde\n❤️ | Rojo",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=4000,
    )

    def __init__(self, canal: discord.TextChannel, mensaje: discord.Message):
        super().__init__()
        self.canal = canal
        self.mensaje = mensaje

    async def on_submit(self, interaction: discord.Interaction):
        # Defer inmediato para evitar que Discord expire la interacción
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        msg_key = str(self.mensaje.id)

        if msg_key not in reaction_roles_data:
            reaction_roles_data[msg_key] = {}

        lineas = [l.strip() for l in self.pares.value.strip().splitlines() if l.strip()]
        errores = []
        configurados = 0

        for linea in lineas:
            if "|" not in linea:
                errores.append(f"Formato inválido: `{linea}`")
                continue

            partes = linea.split("|", 1)
            emoji = partes[0].strip()
            nombre_rol = partes[1].strip()

            # Buscar el rol por nombre (insensible a mayúsculas)
            rol = discord.utils.find(
                lambda r: r.name.lower() == nombre_rol.lower(),
                guild.roles
            )

            if not rol:
                errores.append(f"Rol no encontrado: `{nombre_rol}`")
                continue

            reaction_roles_data[msg_key][emoji] = rol.id

            try:
                await self.mensaje.add_reaction(emoji)
                configurados += 1
            except discord.HTTPException:
                errores.append(f"Emoji inválido: `{emoji}`")

        guardar_reaction_roles(reaction_roles_data)

        resumen = f"✅ {configurados} reaction role(s) configurado(s)."
        if errores:
            resumen += "\n⚠️ Errores:\n" + "\n".join(f"> {e}" for e in errores)

        # followup porque ya se hizo defer
        await interaction.followup.send(resumen, ephemeral=True)


@bot.tree.command(name="reactionroles", description="Configura roles por reacción en un mensaje (ilimitados)")
@app_commands.describe(
    canal="Canal donde está el mensaje",
    mensaje_id="ID del mensaje",
)
async def reactionroles_command(
    interaction: discord.Interaction,
    canal: discord.TextChannel,
    mensaje_id: str,
):
    if await rechazar_si_no_es_owner(interaction):
        return

    try:
        mensaje = await canal.fetch_message(int(mensaje_id))
    except discord.NotFound:
        await interaction.response.send_message("❌ Mensaje no encontrado.", ephemeral=True)
        return
    except ValueError:
        await interaction.response.send_message("❌ ID inválido.", ephemeral=True)
        return

    await interaction.response.send_modal(ReactionRolesModal(canal=canal, mensaje=mensaje))


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return

    msg_key = str(payload.message_id)
    if msg_key not in reaction_roles_data:
        return

    emoji = str(payload.emoji)
    if emoji not in reaction_roles_data[msg_key]:
        return

    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return

    member = guild.get_member(payload.user_id)
    if not member:
        return

    # Quitar todos los otros roles del mismo grupo antes de dar el nuevo
    todos_los_roles_del_grupo = [
        guild.get_role(rid)
        for rid in reaction_roles_data[msg_key].values()
    ]
    roles_a_quitar = [
        r for r in todos_los_roles_del_grupo
        if r and r in member.roles and r.id != reaction_roles_data[msg_key][emoji]
    ]
    if roles_a_quitar:
        await member.remove_roles(*roles_a_quitar)

        # Quitar también las reacciones anteriores del mensaje para mantener consistencia visual
        canal = guild.get_channel(payload.channel_id)
        if canal:
            try:
                mensaje = await canal.fetch_message(payload.message_id)
                for e, rid in reaction_roles_data[msg_key].items():
                    if rid != reaction_roles_data[msg_key][emoji] and e != emoji:
                        try:
                            await mensaje.remove_reaction(e, member)
                        except discord.HTTPException:
                            pass
            except discord.HTTPException:
                pass

    role = guild.get_role(reaction_roles_data[msg_key][emoji])
    if role:
        await member.add_roles(role)


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return

    msg_key = str(payload.message_id)
    if msg_key not in reaction_roles_data:
        return

    emoji = str(payload.emoji)
    if emoji not in reaction_roles_data[msg_key]:
        return

    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return

    member = guild.get_member(payload.user_id)
    if not member:
        return

    role = guild.get_role(reaction_roles_data[msg_key][emoji])
    if role:
        await member.remove_roles(role)

# ─── Bot listo ────────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user} (ID: {bot.user.id})")
    try:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.clear_commands(guild=guild)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        print(f"🔄 {len(synced)} comando(s) sincronizado(s)")
    except Exception as e:
        print(f"❌ Error: {e}")


TOKEN = os.getenv("TOKEN")
webserver.keep_alive()  # Iniciar el servidor web para mantener el bot activo
bot.run(TOKEN)