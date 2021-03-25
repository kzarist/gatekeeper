from discord import Client as DiscordClient
from discord import Message, AsyncWebhookAdapter, Webhook, Intents
import slixmpp
import logging
import aiohttp


class GateKeeper:
    logger = logging.getLogger("gatekeeper")

    def __init__(self):
        self.discord = None
        self.xmpp = None

    async def discord_message(self, message: Message):
        if self.xmpp:
            nick = message.author.name
            content = message.content
            xmpp_message = f"{nick} : {content}"
            self.xmpp.send_message(
                mto=self.xmpp.channel, mbody=xmpp_message, mtype="groupchat"
            )
            for attachment in message.attachments:
                await self.xmpp_embed_file(attachment)

    async def xmpp_embed_file(self, file):
        message = self.xmpp.make_message(self.xmpp.channel)
        message["body"] = file.url
        message["type"] = "groupchat"
        message["oob"]["url"] = file.url
        message.send()

    async def xmpp_message(self, message: slixmpp.stanza.Message):
        if self.discord:
            async with aiohttp.ClientSession() as session:
                webhook = Webhook.from_url(
                    self.discord.webhook_url, adapter=AsyncWebhookAdapter(session)
                )
                username = message.get_mucnick()
                await webhook.send(
                    str(message["body"]).replace("@everyone", "@everyjuan"),
                    username=username,
                )


class DiscordKeeper(DiscordClient):
    intents = Intents(messages=True, guilds=True, members=True)
    logger = logging.getLogger("discordkeeper")

    def __init__(self, channel_id: int, webhook_url: str, mitm):
        super().__init__(intents=self.intents)
        self.channel_id = channel_id
        self.mitm = mitm
        mitm.discord = self
        self.webhook_url = webhook_url

    async def on_ready(self):
        self.logger.info(f"logged in as {self.user}")

    async def on_message(self, message: Message):
        if message.author.bot:
            return
        if message.author == self.user:
            return
        if message.channel.id == self.channel_id:
            await self.mitm.discord_message(message)


class XmppKeeper(slixmpp.ClientXMPP):
    logger = logging.getLogger("xmppkeeper")

    def __init__(self, nick, channel: str, mitm: GateKeeper, **kwargs):
        super().__init__(**kwargs)
        self.avatar = None
        self.avatar_info = None
        self.nick = nick
        self.channel = channel
        self.mitm = mitm
        mitm.xmpp = self
        self.register_plugins()
        self.register_events()
        self.logger.info(f"logged as {nick}")

    def register_plugins(self):
        self.register_plugin("xep_0030")
        self.register_plugin("xep_0060")
        self.register_plugin("xep_0054")
        self.register_plugin("xep_0045")
        self.register_plugin("xep_0066")
        self.register_plugin("xep_0084")
        self.register_plugin("xep_0153")
        self.register_plugin("xep_0363")

    def register_events(self):
        self.add_event_handler("session_start", self.on_ready)
        self.add_event_handler("groupchat_message", self.on_message)
        self.add_event_handler("disconnected", lambda _: self.connect())

    async def on_ready(self, _):
        self.send_presence()
        await self.get_roster()
        await self.plugin["xep_0045"].join_muc(self.channel, self.nick)
        self.load_avatar()
        await self.publish_avatar()

    def load_avatar(self):
        with open("avatar.png", "rb") as avatar_file:
            avatar = avatar_file.read()

        avatar_type = "image/png"
        avatar_id = self.plugin["xep_0084"].generate_id(avatar)
        avatar_bytes = len(avatar)

        self.avatar = avatar
        self.avatar_info = {
            "id": avatar_id,
            "type": avatar_type,
            "bytes": avatar_bytes,
        }

    async def publish_avatar(self):
        avatar = self.avatar
        info = self.avatar_info
        avatar_type = info["type"]

        await self.plugin["xep_0153"].set_avatar(
            avatar=avatar,
            mtype=avatar_type,
        )
        await self.plugin["xep_0084"].publish_avatar_metadata([info])
        await self.plugin["xep_0084"].publish_avatar(avatar)

    async def on_message(self, message):
        if message["type"] in ("groupchat"):
            if message.get_mucroom() == self.channel:
                if "urn:xmpp:message-correct:0" in str(message):
                    return
                if message["mucnick"] == self.nick:
                    return
                await self.mitm.xmpp_message(message)
