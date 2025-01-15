import discord
from discord.ext import commands, tasks
import requests
import datetime

# ===============================================================
# Configuration
# ===============================================================

DISCORD_BOT_TOKEN = "MTMxMjQwODY4MDgwOTEwMzQ5MQ.GL0EmS.MByZiAGqfI2X8BdVsPtol9kc8h8nc8LGw1sTcw"
RIOT_API_KEY = "RGAPI-f5672a44-e896-46f0-a8e9-3f6afe819b79"

# Les 5 joueurs à suivre : PUUID -> (Pseudo, ChannelName)
PLAYERS = {
    'dWdxbiTXvLuzuEO0NqyH8Z3w5XvfMU37kUwOx-a-3bRQtl6DVn3THQdb9oFUvMfgYuehbj2CpBNz4g': ("Nireo", "nireo"),
    'LpWjpjFNxvRMZpvrnXmr7VW0Ck_QUmHMJ7Jg4wV-IP2VJqRj1zJMdHPMLEoJOUYyvu8GhCVPb6mTzg': ("Peche", "peche"),
    'MWvpDXGzb6qIbkx4Cfuu5Be_krbIfoJEe5YTC4-nG2hzPXVOuYCqq44BxkQBYUvNh_CYN-yLpRSLGQ': ("Jawa",  "jawa"),
    '1gYznPKTqzxc9kq-Y5FMzs0s7ofbd7MaTUAb-ltWqunBUkWQdV3RrsuuRDN9WRdESz_HuQ55pb1DnQ': ("Kross", "kross"),
    '8c6rzHOn_q0xhOPwo26tJ_cMsopeDFrcZ2aaaJcf9vV5rohLR_jyTx68-lqJ2fQmc0SZ0i461UTZFQ': ("Iench", "iench")
}

LEADERBOARD_CHANNEL_NAME = "leaderboard"

# URLs de l'API Riot (à adapter si nécessaire)
RIOT_RANKED_URL = "https://euw1.api.riotgames.com/lol/league/v4/entries/by-summoner/{summoner_id}"
RIOT_SUMMONER_URL = "https://euw1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
RIOT_MATCHLIST_URL = "https://europe.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?start=0&count=10"
RIOT_MATCH_URL = "https://europe.api.riotgames.com/lol/match/v5/matches/{match_id}"

# ===============================================================
# Structures de données
# ===============================================================

player_soloq_data = {}    # infos SoloQ (rank, LP, W/L)
last_checked_match = {}   # pour ne pas compter deux fois le même match
champion_challenges = {   # défis par champion
    puuid: {} for puuid in PLAYERS
}

# ===============================================================
# Fonctions utilitaires pour l'API Riot
# ===============================================================

def get_summoner_id_by_puuid(puuid: str):
    url = RIOT_SUMMONER_URL.format(puuid=puuid)
    headers = {"X-Riot-Token": RIOT_API_KEY}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        return data["id"]  # summonerId
    else:
        print(f"Erreur get_summoner_id_by_puuid pour {puuid}: {response.text}")
        return None

def get_ranked_stats(summoner_id: str):
    url = RIOT_RANKED_URL.format(summoner_id=summoner_id)
    headers = {"X-Riot-Token": RIOT_API_KEY}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        for queue_data in data:
            if queue_data["queueType"] == "RANKED_SOLO_5x5":
                return {
                    "tier": queue_data["tier"],
                    "rank": queue_data["rank"],
                    "lp": queue_data["leaguePoints"],
                    "wins": queue_data["wins"],
                    "losses": queue_data["losses"]
                }
        # Si pas de file soloQ trouvée
        return {"tier": "UNRANKED", "rank": "", "lp": 0, "wins": 0, "losses": 0}
    else:
        print(f"Erreur get_ranked_stats: {response.text}")
        return None

def get_recent_match_ids(puuid: str, count: int = 1):
    url = RIOT_MATCHLIST_URL.format(puuid=puuid)
    headers = {"X-Riot-Token": RIOT_API_KEY}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        return data[:count]
    else:
        print(f"Erreur get_recent_match_ids pour {puuid}: {response.text}")
        return []

def get_match_data(match_id: str):
    url = RIOT_MATCH_URL.format(match_id=match_id)
    headers = {"X-Riot-Token": RIOT_API_KEY}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Erreur get_match_data pour {match_id}: {response.text}")
        return None

# ===============================================================
# Configuration des Intents
# ===============================================================

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True

# ===============================================================
# Classe MyBot
# ===============================================================

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def on_ready(self):
        """Quand le bot est prêt."""
        print(f"Bot connecté en tant que {self.user} (id={self.user.id})")

        # Lancement des tâches
        self.update_leaderboard.start()
        self.check_recent_matches.start()

    # ==========================================
    # Tâche 1 : update_leaderboard (toutes les 2h)
    # ==========================================
    @tasks.loop(hours=2)
    async def update_leaderboard(self):
        await self.wait_until_ready()
        print("[TASK] Mise à jour du leaderboard")

        if not self.guilds:
            return
        guild = self.guilds[0]

        leaderboard_channel = discord.utils.get(guild.text_channels, name=LEADERBOARD_CHANNEL_NAME)
        if leaderboard_channel is None:
            print(f"Le salon '{LEADERBOARD_CHANNEL_NAME}' n'existe pas.")
            return

        leaderboard_lines = []
        for puuid, (pseudo, channel_name) in PLAYERS.items():
            summoner_id = get_summoner_id_by_puuid(puuid)
            if not summoner_id:
                continue
            stats = get_ranked_stats(summoner_id)
            if not stats:
                continue

            player_soloq_data[puuid] = {
                "rank": f"{stats['tier']} {stats['rank']}",
                "lp": stats["lp"],
                "wins": stats["wins"],
                "losses": stats["losses"]
            }

            line = (f"**{pseudo}** : {stats['tier']} {stats['rank']} - "
                    f"{stats['lp']} LP (W:{stats['wins']}/L:{stats['losses']})")
            leaderboard_lines.append(line)

        if leaderboard_lines:
            message = "\n".join(leaderboard_lines)
            timestamp = int(datetime.datetime.now().timestamp())
            await leaderboard_channel.send(
                f"**Leaderboard SoloQ** (MAJ <t:{timestamp}>)\n\n{message}"
            )
        else:
            await leaderboard_channel.send("Aucune donnée de leaderboard disponible.")

    # ==============================================
    # Tâche 2 : check_recent_matches (toutes les 5min)
    # ==============================================
    @tasks.loop(minutes=5)
    async def check_recent_matches(self):
        await self.wait_until_ready()
        print("[TASK] Vérification des derniers matchs")

        if not self.guilds:
            return
        guild = self.guilds[0]

        for puuid, (pseudo, channel_name) in PLAYERS.items():
            match_ids = get_recent_match_ids(puuid, count=1)
            if not match_ids:
                continue

            latest_match_id = match_ids[0]

            # Si déjà vérifié, on passe
            if last_checked_match.get(puuid) == latest_match_id:
                continue

            # On marque ce match comme vérifié
            last_checked_match[puuid] = latest_match_id

            match_data = get_match_data(latest_match_id)
            if not match_data:
                continue

            participants = match_data["info"]["participants"]
            champion_played = None
            for participant in participants:
                if participant["puuid"] == puuid:
                    champion_played = participant["championName"]
                    break

            if not champion_played:
                continue

            # Si le champion est suivi dans champion_challenges
            if champion_played in champion_challenges[puuid]:
                champion_challenges[puuid][champion_played] -= 1
                nb_restants = champion_challenges[puuid][champion_played]

                player_channel = discord.utils.get(guild.text_channels, name=channel_name)
                if player_channel:
                    if nb_restants > 0:
                        await player_channel.send(
                            f"{pseudo}, tu viens de jouer **{champion_played}**. "
                            f"Il te reste **{nb_restants}** partie(s) à jouer."
                        )
                    else:
                        await player_channel.send(
                            f"{pseudo}, tu viens de jouer **{champion_played}**. "
                            f"Ton objectif pour ce champion est **terminé** !"
                        )
                        # Optionnel : on peut enlever le champion du dict
                        # del champion_challenges[puuid][champion_played]

# ===============================================================
# Instanciation du bot
# ===============================================================
bot = MyBot()

# ===============================================================
# Commandes préfixées
# ===============================================================

# Ici, on fait un "groupe" u pour taper : !u setchampion <champion> <nb_parties>
@bot.group()
async def u(ctx):
    """
    Groupe de commandes appelées via !u ...
    """
    if ctx.invoked_subcommand is None:
        await ctx.send("Utilisez : **!u setchampion <champion> <nb_parties>**")

@u.command(name="setchampion")
async def setchampion_cmd(ctx, champion: str, nb_parties: int):
    """
    Commande : !u setchampion <champion> <nb_parties>
    À taper dans le salon dédié (ex: #nireo).
    """
    channel_name = ctx.channel.name.lower()
    puuid_found = None

    for puuid, (pseudo, pchannel) in PLAYERS.items():
        if pchannel.lower() == channel_name:
            puuid_found = puuid
            break

    if not puuid_found:
        await ctx.send("Vous devez utiliser cette commande dans votre salon dédié.")
        return

    # On met à jour le défi
    champion_challenges[puuid_found][champion] = nb_parties
    await ctx.send(
        f"Défi mis à jour pour **{champion}** : il te reste **{nb_parties}** parties à jouer."
    )

# ===============================================================
# Lancement du bot
# ===============================================================
if __name__ == "__main__":
    bot.run(DISCORD_BOT_TOKEN)
