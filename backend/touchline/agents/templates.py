"""Offline, deterministic multilingual writer.

Used when no model is configured, when an agent times out, or when the Guardian
rejects a model twice. Every placeholder that carries a number is bound to a Fact,
and the renderer records which facts were used, so template output is cited and
Guardian-safe by construction.
"""

from __future__ import annotations

import random
import string
from dataclasses import dataclass

from touchline.agents.context import MomentContext
from touchline.models import Fact, Mode, Side, format_value

LANGS = ("en", "es", "fr", "pt", "ar", "ja")
COMMA_DECIMAL = {"es", "fr", "pt"}

# ----------------------------------------------------------------------------- phrase tables

T: dict[str, dict] = {
    "en": {
        "states": {
            "opener": "Breakthrough!",
            "equaliser": "Level again!",
            "go_ahead": "In front!",
            "extend_lead": "Breathing room.",
            "pull_back": "Game on!",
            "comeback": "Comeback complete!",
            "late_winner": "Late drama!",
            "none": "",
        },
        "quality": {
            "high": "a chance you expect to score",
            "mid": "a decent opportunity",
            "low": "a low-percentage finish",
        },
        "outcome": {
            "saved": "the keeper saved it",
            "blocked": "it was blocked",
            "off_target": "it went wide",
            "goal": "scored",
        },
        "verdict_for": "the chances back up the scoreline",
        "verdict_against": "the scoreline is running ahead of the chances",
        "club_good": "Good news for {club}: ",
        "club_bad": "Worrying for {club}: ",
        "player_focus": "{focus} watch: ",
        "data": "Data",
        "head": {
            "goal": "{player} scores for {team}",
            "big_chance": "Huge chance for {player}",
            "shot_on_target": "{player} lets fly",
            "red_card": "{team} down to {players}",
            "yellow_card": "Booking for {player}",
            "momentum_swing": "Momentum swings to {team}",
            "pressure_shift": "{team} crank up the press",
            "chaos": "The game breaks open",
            "control": "{team} take control",
            "sprint": "{player} at full speed",
            "pass_of_match": "Pass of the match so far",
            "milestone_distance": "{player} leads the running",
            "milestone_passes": "{player} running the game",
            "phase": "{ht_ft}: {home} {score} {away}",
        },
        "why": {
            "goal": "{state} {player} converts a {xg} xG chance, {quality}, struck at {speed}. It's {score}, and xG reads {team} {xg_team}, {opp} {xg_opp}: {verdict}.",
            "big_chance": "{player} had a {xg} xG chance from {dist} and {outcome}. Chances like that go in about {xg_pct} times in 100, so {team} will feel this one.",
            "shot_on_target": "{player} tests the keeper with a {speed} strike. At that speed the goalkeeper has a fraction of a second to react.",
            "red_card": "{team} are down to {players} with {minutes_left} left. They had {poss} of the ball in the previous ten minutes; expect {opp} to take over now.",
            "yellow_card": "{player} is booked ({team} yellow cards: {yellows}). It limits how aggressively they can defend from here.",
            "momentum_swing": "Momentum has swung from {mom_prev} to {mom_now} in five minutes. {team} have had {poss} of the ball in that spell. Shots in that spell: {shots}.",
            "pressure_shift": "{team} are pressing much higher: PPDA has dropped from {ppda_prev} to {ppda_now}, so {opp} get far fewer passes before losing the ball.",
            "chaos": "The Control vs Chaos index jumped from {chaos_prev} to {chaos}, with {turnovers} turnovers in five minutes. Nobody can keep the ball, which is when mistakes and goals happen.",
            "control": "{team} have settled it down: the Control vs Chaos index is {chaos}, with {poss} possession and {acc} pass accuracy in the last five minutes.",
            "sprint": "{player} just hit {top_speed}. Pace like that forces defenders to drop deeper to protect the space behind.",
            "pass_of_match": "{player} completed a pass rated {diff} for difficulty: {pdist} through {lane} opponents in the lane. {player_short} is at {acc} passing accuracy today.",
            "milestone_distance": "{player} is the first to cover {km} today, a sign of how much {team} are working off the ball.",
            "milestone_passes": "{player} has made {passes} passes at {acc} accuracy; {team}'s play is running through them.",
            "phase": "{ht_ft}: {home} {score} {away}. {home} have {poss_home} possession, xG is {xg_home} to {xg_away} and shots {shots_home} to {shots_away}.",
        },
        "fan": {
            "goal": "{state} {player} scores! It's {score}.",
            "big_chance": "So close! {player} should have scored there.",
            "shot_on_target": "What a hit from {player}!",
            "red_card": "Red card! {team} are down to {players}.",
            "yellow_card": "{player} goes into the book.",
            "momentum_swing": "{team} are on top now, and the crowd can feel it.",
            "pressure_shift": "{team} are hunting the ball high up the pitch.",
            "chaos": "End-to-end! Anything can happen now.",
            "control": "{team} have the ball and the game under control.",
            "sprint": "{player} is flying! {top_speed}!",
            "pass_of_match": "What a pass from {player}!",
            "milestone_distance": "{player} never stops running.",
            "milestone_passes": "Everything goes through {player} today.",
            "phase": "{ht_ft}: {home} {score} {away}.",
        },
    },
    "es": {
        "states": {
            "opener": "¡Se abre el marcador!",
            "equaliser": "¡Empate!",
            "go_ahead": "¡Por delante!",
            "extend_lead": "Más distancia.",
            "pull_back": "¡Hay partido!",
            "comeback": "¡Remontada completada!",
            "late_winner": "¡Drama al final!",
            "none": "",
        },
        "quality": {
            "high": "una ocasión que se espera marcar",
            "mid": "una oportunidad decente",
            "low": "un remate de baja probabilidad",
        },
        "outcome": {
            "saved": "el portero la detuvo",
            "blocked": "se la bloquearon",
            "off_target": "se fue fuera",
            "goal": "marcó",
        },
        "verdict_for": "las ocasiones respaldan el marcador",
        "verdict_against": "el marcador va por delante de las ocasiones",
        "club_good": "Buenas noticias para el {club}: ",
        "club_bad": "Preocupante para el {club}: ",
        "player_focus": "Foco en {focus}: ",
        "data": "Datos",
        "head": {
            "goal": "Gol de {player} para el {team}",
            "big_chance": "Ocasión enorme para {player}",
            "shot_on_target": "{player} prueba al portero",
            "red_card": "El {team} se queda con {players}",
            "yellow_card": "Amarilla para {player}",
            "momentum_swing": "El impulso cambia hacia el {team}",
            "pressure_shift": "El {team} adelanta la presión",
            "chaos": "El partido se rompe",
            "control": "El {team} toma el control",
            "sprint": "{player} a toda velocidad",
            "pass_of_match": "El pase del partido",
            "milestone_distance": "{player} lidera en kilómetros",
            "milestone_passes": "{player} dirige el juego",
            "phase": "{ht_ft}: {home} {score} {away}",
        },
        "why": {
            "goal": "{state} {player} convierte una ocasión de {xg} xG, {quality}, con un disparo a {speed}. Va {score}, y el xG marca {team} {xg_team}, {opp} {xg_opp}: {verdict}.",
            "big_chance": "{player} tuvo una ocasión de {xg} xG desde {dist} y {outcome}. Ocasiones así entran unas {xg_pct} de cada 100, así que el {team} la va a lamentar.",
            "shot_on_target": "{player} exige al portero con un disparo a {speed}. A esa velocidad el portero apenas tiene una fracción de segundo para reaccionar.",
            "red_card": "El {team} se queda con {players} y faltan {minutes_left}. Tuvo el {poss} del balón en los diez minutos anteriores; ahora el {opp} debería dominar.",
            "yellow_card": "{player} ve la amarilla (amarillas del {team}: {yellows}). Eso limita lo agresivos que pueden ser defendiendo.",
            "momentum_swing": "El impulso ha pasado de {mom_prev} a {mom_now} en cinco minutos. El {team} ha tenido el {poss} del balón en ese tramo. Tiros en ese tramo: {shots}.",
            "pressure_shift": "El {team} presiona mucho más arriba: el PPDA ha bajado de {ppda_prev} a {ppda_now}, así que el {opp} da muchos menos pases antes de perder el balón.",
            "chaos": "El índice Control vs Caos saltó de {chaos_prev} a {chaos}, con {turnovers} pérdidas en cinco minutos. Nadie retiene el balón: es cuando llegan los errores y los goles.",
            "control": "El {team} ha calmado el partido: el índice Control vs Caos está en {chaos}, con un {poss} de posesión y un {acc} de acierto en el pase en los últimos cinco minutos.",
            "sprint": "{player} acaba de alcanzar {top_speed}. Esa velocidad obliga a los defensas a retroceder para proteger la espalda.",
            "pass_of_match": "{player} completó un pase con dificultad {diff}: {pdist} con {lane} rivales en la línea de pase. {player_short} lleva un {acc} de acierto hoy.",
            "milestone_distance": "{player} es el primero en recorrer {km} hoy, señal del trabajo sin balón del {team}.",
            "milestone_passes": "{player} lleva {passes} pases con un {acc} de acierto; el juego del {team} pasa por sus botas.",
            "phase": "{ht_ft}: {home} {score} {away}. El {home} tiene un {poss_home} de posesión, el xG es {xg_home} a {xg_away} y los tiros {shots_home} a {shots_away}.",
        },
        "fan": {
            "goal": "{state} ¡Gol de {player}! {score}.",
            "big_chance": "¡Uf! {player} tuvo que marcar ahí.",
            "shot_on_target": "¡Qué disparo de {player}!",
            "red_card": "¡Roja! El {team} se queda con {players}.",
            "yellow_card": "Amarilla para {player}.",
            "momentum_swing": "El {team} manda ahora y la grada lo siente.",
            "pressure_shift": "El {team} va a por el balón arriba.",
            "chaos": "¡Ida y vuelta! Puede pasar cualquier cosa.",
            "control": "El {team} tiene el balón y el partido bajo control.",
            "sprint": "¡{player} vuela! ¡{top_speed}!",
            "pass_of_match": "¡Qué pase de {player}!",
            "milestone_distance": "{player} no para de correr.",
            "milestone_passes": "Todo pasa por {player} hoy.",
            "phase": "{ht_ft}: {home} {score} {away}.",
        },
    },
    "fr": {
        "states": {
            "opener": "Ouverture du score !",
            "equaliser": "Égalisation !",
            "go_ahead": "Devant !",
            "extend_lead": "De l'air.",
            "pull_back": "Le match est relancé !",
            "comeback": "Remontada accomplie !",
            "late_winner": "Scénario fou !",
            "none": "",
        },
        "quality": {
            "high": "une occasion qu'on s'attend à marquer",
            "mid": "une occasion correcte",
            "low": "une frappe à faible probabilité",
        },
        "outcome": {
            "saved": "le gardien a sauvé",
            "blocked": "elle a été contrée",
            "off_target": "elle est passée à côté",
            "goal": "a marqué",
        },
        "verdict_for": "les occasions confirment le score",
        "verdict_against": "le score est en avance sur les occasions",
        "club_good": "Bonne nouvelle pour {club} : ",
        "club_bad": "Inquiétant pour {club} : ",
        "player_focus": "Focus {focus} : ",
        "data": "Données",
        "head": {
            "goal": "But de {player} pour {team}",
            "big_chance": "Énorme occasion pour {player}",
            "shot_on_target": "{player} déclenche",
            "red_card": "{team} à {players}",
            "yellow_card": "Carton jaune pour {player}",
            "momentum_swing": "L'élan bascule vers {team}",
            "pressure_shift": "{team} pressent plus haut",
            "chaos": "Le match s'emballe",
            "control": "{team} prennent le contrôle",
            "sprint": "{player} à pleine vitesse",
            "pass_of_match": "La passe du match",
            "milestone_distance": "{player} en tête des kilomètres",
            "milestone_passes": "{player} dirige le jeu",
            "phase": "{ht_ft} : {home} {score} {away}",
        },
        "why": {
            "goal": "{state} {player} convertit une occasion à {xg} xG, {quality}, frappée à {speed}. C'est {score}, et l'xG indique {team} {xg_team}, {opp} {xg_opp} : {verdict}.",
            "big_chance": "{player} avait une occasion à {xg} xG à {dist} et {outcome}. Ce genre d'occasion finit au fond environ {xg_pct} fois sur 100 : {team} va le regretter.",
            "shot_on_target": "{player} teste le gardien d'une frappe à {speed}. À cette vitesse, le gardien n'a qu'une fraction de seconde pour réagir.",
            "red_card": "{team} jouent à {players} avec {minutes_left} à jouer. Ils avaient {poss} du ballon sur les dix minutes précédentes ; {opp} devraient prendre le dessus.",
            "yellow_card": "{player} est averti (cartons jaunes pour {team} : {yellows}). Cela limite leur agressivité défensive.",
            "momentum_swing": "L'élan est passé de {mom_prev} à {mom_now} en cinq minutes. {team} ont eu {poss} du ballon sur cette période. Tirs sur la période : {shots}.",
            "pressure_shift": "{team} pressent beaucoup plus haut : le PPDA est passé de {ppda_prev} à {ppda_now}, donc {opp} font bien moins de passes avant de perdre le ballon.",
            "chaos": "L'indice Contrôle vs Chaos est passé de {chaos_prev} à {chaos}, avec {turnovers} pertes de balle en cinq minutes. Personne ne garde le ballon : c'est là que naissent les erreurs et les buts.",
            "control": "{team} ont calmé le jeu : l'indice Contrôle vs Chaos est à {chaos}, avec {poss} de possession et {acc} de passes réussies sur les cinq dernières minutes.",
            "sprint": "{player} vient d'atteindre {top_speed}. Une telle vitesse oblige les défenseurs à reculer pour protéger la profondeur.",
            "pass_of_match": "{player} a réussi une passe notée {diff} en difficulté : {pdist} avec {lane} adversaires sur la trajectoire. {player_short} est à {acc} de passes réussies.",
            "milestone_distance": "{player} est le premier à parcourir {km} aujourd'hui, signe du travail de {team} sans ballon.",
            "milestone_passes": "{player} a tenté {passes} passes avec {acc} de réussite ; le jeu de {team} passe par lui.",
            "phase": "{ht_ft} : {home} {score} {away}. {home} ont {poss_home} de possession, l'xG est de {xg_home} contre {xg_away} et les tirs {shots_home} contre {shots_away}.",
        },
        "fan": {
            "goal": "{state} But de {player} ! {score}.",
            "big_chance": "Si proche ! {player} devait marquer.",
            "shot_on_target": "Quelle frappe de {player} !",
            "red_card": "Rouge ! {team} à {players}.",
            "yellow_card": "Jaune pour {player}.",
            "momentum_swing": "{team} dominent et le stade le sent.",
            "pressure_shift": "{team} chassent le ballon très haut.",
            "chaos": "Ça va dans tous les sens !",
            "control": "{team} ont le ballon et le match en main.",
            "sprint": "{player} s'envole ! {top_speed} !",
            "pass_of_match": "Quelle passe de {player} !",
            "milestone_distance": "{player} ne s'arrête jamais.",
            "milestone_passes": "Tout passe par {player} aujourd'hui.",
            "phase": "{ht_ft} : {home} {score} {away}.",
        },
    },
    "pt": {
        "states": {
            "opener": "Abre o placar!",
            "equaliser": "Empate!",
            "go_ahead": "Na frente!",
            "extend_lead": "Mais folga.",
            "pull_back": "O jogo está vivo!",
            "comeback": "Virada completa!",
            "late_winner": "Drama no fim!",
            "none": "",
        },
        "quality": {
            "high": "uma chance que se espera converter",
            "mid": "uma oportunidade razoável",
            "low": "uma finalização de baixa probabilidade",
        },
        "outcome": {
            "saved": "o goleiro defendeu",
            "blocked": "foi bloqueada",
            "off_target": "foi para fora",
            "goal": "marcou",
        },
        "verdict_for": "as chances confirmam o placar",
        "verdict_against": "o placar está à frente das chances",
        "club_good": "Boa notícia para o {club}: ",
        "club_bad": "Preocupante para o {club}: ",
        "player_focus": "Foco em {focus}: ",
        "data": "Dados",
        "head": {
            "goal": "Gol de {player} para o {team}",
            "big_chance": "Chance enorme para {player}",
            "shot_on_target": "{player} solta a bomba",
            "red_card": "{team} fica com {players}",
            "yellow_card": "Amarelo para {player}",
            "momentum_swing": "O momento muda para o {team}",
            "pressure_shift": "O {team} sobe a pressão",
            "chaos": "O jogo fica aberto",
            "control": "O {team} assume o controle",
            "sprint": "{player} em velocidade máxima",
            "pass_of_match": "O passe do jogo",
            "milestone_distance": "{player} lidera na distância",
            "milestone_passes": "{player} comanda o jogo",
            "phase": "{ht_ft}: {home} {score} {away}",
        },
        "why": {
            "goal": "{state} {player} converte uma chance de {xg} xG, {quality}, com chute a {speed}. Está {score}, e o xG mostra {team} {xg_team}, {opp} {xg_opp}: {verdict}.",
            "big_chance": "{player} teve uma chance de {xg} xG a {dist} e {outcome}. Chances assim entram cerca de {xg_pct} vezes em 100, então o {team} vai lamentar.",
            "shot_on_target": "{player} testa o goleiro com um chute a {speed}. Nessa velocidade o goleiro tem uma fração de segundo para reagir.",
            "red_card": "O {team} fica com {players} e faltam {minutes_left}. Teve {poss} da posse nos dez minutos anteriores; agora o {opp} deve dominar.",
            "yellow_card": "{player} leva amarelo (amarelos do {team}: {yellows}). Isso limita a agressividade defensiva.",
            "momentum_swing": "O momento passou de {mom_prev} para {mom_now} em cinco minutos. O {team} teve {poss} da bola nesse período. Finalizações no período: {shots}.",
            "pressure_shift": "O {team} pressiona muito mais alto: o PPDA caiu de {ppda_prev} para {ppda_now}, então o {opp} troca bem menos passes antes de perder a bola.",
            "chaos": "O índice Controle vs Caos saltou de {chaos_prev} para {chaos}, com {turnovers} perdas de posse em cinco minutos. Ninguém segura a bola: é quando surgem erros e gols.",
            "control": "O {team} acalmou o jogo: o índice Controle vs Caos está em {chaos}, com {poss} de posse e {acc} de acerto nos passes nos últimos cinco minutos.",
            "sprint": "{player} acaba de atingir {top_speed}. Essa velocidade obriga os zagueiros a recuar para proteger as costas.",
            "pass_of_match": "{player} completou um passe com dificuldade {diff}: {pdist} com {lane} adversários na linha do passe. {player_short} está com {acc} de acerto hoje.",
            "milestone_distance": "{player} é o primeiro a percorrer {km} hoje, sinal do trabalho sem bola do {team}.",
            "milestone_passes": "{player} já deu {passes} passes com {acc} de acerto; o jogo do {team} passa por ele.",
            "phase": "{ht_ft}: {home} {score} {away}. O {home} tem {poss_home} de posse, o xG é {xg_home} a {xg_away} e as finalizações {shots_home} a {shots_away}.",
        },
        "fan": {
            "goal": "{state} Gol de {player}! {score}.",
            "big_chance": "Quase! {player} tinha que marcar.",
            "shot_on_target": "Que chute de {player}!",
            "red_card": "Vermelho! O {team} fica com {players}.",
            "yellow_card": "Amarelo para {player}.",
            "momentum_swing": "O {team} domina agora e a torcida sente.",
            "pressure_shift": "O {team} caça a bola lá na frente.",
            "chaos": "Lá e cá! Tudo pode acontecer.",
            "control": "O {team} tem a bola e o jogo sob controle.",
            "sprint": "{player} voando! {top_speed}!",
            "pass_of_match": "Que passe de {player}!",
            "milestone_distance": "{player} não para de correr.",
            "milestone_passes": "Tudo passa por {player} hoje.",
            "phase": "{ht_ft}: {home} {score} {away}.",
        },
    },
    "ar": {
        "states": {
            "opener": "افتتاح التسجيل!",
            "equaliser": "التعادل!",
            "go_ahead": "في المقدمة!",
            "extend_lead": "فارق مريح.",
            "pull_back": "المباراة اشتعلت!",
            "comeback": "عودة مكتملة!",
            "late_winner": "دراما في الختام!",
            "none": "",
        },
        "quality": {"high": "فرصة يُتوقع تسجيلها", "mid": "فرصة جيدة", "low": "تسديدة منخفضة الاحتمال"},
        "outcome": {
            "saved": "تصدى لها الحارس",
            "blocked": "صُدّت",
            "off_target": "ذهبت خارج المرمى",
            "goal": "سجل",
        },
        "verdict_for": "الفرص تدعم النتيجة",
        "verdict_against": "النتيجة تسبق الفرص",
        "club_good": "خبر سار لـ{club}: ",
        "club_bad": "مقلق لـ{club}: ",
        "player_focus": "تركيز على {focus}: ",
        "data": "البيانات",
        "head": {
            "goal": "{player} يسجل لـ{team}",
            "big_chance": "فرصة كبيرة لـ{player}",
            "shot_on_target": "تسديدة قوية من {player}",
            "red_card": "{team} بـ{players} لاعبين",
            "yellow_card": "بطاقة صفراء لـ{player}",
            "momentum_swing": "الزخم يتحول إلى {team}",
            "pressure_shift": "{team} يرفع الضغط",
            "chaos": "المباراة تنفتح",
            "control": "{team} يفرض السيطرة",
            "sprint": "{player} بأقصى سرعة",
            "pass_of_match": "تمريرة المباراة",
            "milestone_distance": "{player} الأكثر ركضًا",
            "milestone_passes": "{player} يدير اللعب",
            "phase": "{ht_ft}: {home} {score} {away}",
        },
        "why": {
            "goal": "{state} {player} يحول فرصة قيمتها {xg} xG، {quality}، بتسديدة سرعتها {speed}. النتيجة {score}، والأهداف المتوقعة: {team} {xg_team}، {opp} {xg_opp}، أي أن {verdict}.",
            "big_chance": "أتيحت لـ{player} فرصة قيمتها {xg} xG من مسافة {dist} لكن {outcome}. مثل هذه الفرص تُسجل نحو {xg_pct} مرة من 100، لذا سيندم {team} عليها.",
            "shot_on_target": "{player} يختبر الحارس بتسديدة سرعتها {speed}. بهذه السرعة لا يملك الحارس سوى جزء من الثانية للتفاعل.",
            "red_card": "{team} يكمل بـ{players} لاعبين مع تبقي {minutes_left}. استحوذ على {poss} من الكرة في الدقائق العشر السابقة؛ والآن يُتوقع أن يسيطر {opp}.",
            "yellow_card": "إنذار لـ{player} (إنذارات {team}: {yellows}). هذا يحد من شراسة دفاعهم.",
            "momentum_swing": "تحول الزخم من {mom_prev} إلى {mom_now} في خمس دقائق. استحوذ {team} على {poss} من الكرة في تلك الفترة. التسديدات في تلك الفترة: {shots}.",
            "pressure_shift": "{team} يضغط أعلى بكثير: انخفض مؤشر PPDA من {ppda_prev} إلى {ppda_now}، أي أن {opp} يمرر أقل بكثير قبل فقدان الكرة.",
            "chaos": "قفز مؤشر السيطرة مقابل الفوضى من {chaos_prev} إلى {chaos} مع {turnovers} فقدانًا للكرة في خمس دقائق. لا أحد يحتفظ بالكرة، وهنا تأتي الأخطاء والأهداف.",
            "control": "{team} هدّأ الإيقاع: مؤشر السيطرة مقابل الفوضى عند {chaos}، مع استحواذ {poss} ودقة تمرير {acc} في آخر خمس دقائق.",
            "sprint": "{player} وصل للتو إلى {top_speed}. هذه السرعة تجبر المدافعين على التراجع لحماية المساحة خلفهم.",
            "pass_of_match": "أكمل {player} تمريرة بصعوبة {diff}: مسافة {pdist} مع {lane} منافسين في مسار الكرة. دقة تمرير {player_short} اليوم {acc}.",
            "milestone_distance": "{player} أول من يقطع {km} اليوم، دليل على عمل {team} دون كرة.",
            "milestone_passes": "قام {player} بـ{passes} تمريرة بدقة {acc}؛ لعب {team} يمر عبره.",
            "phase": "{ht_ft}: {home} {score} {away}. استحواذ {home} {poss_home}، والأهداف المتوقعة {xg_home} مقابل {xg_away}، والتسديدات {shots_home} مقابل {shots_away}.",
        },
        "fan": {
            "goal": "{state} هدف لـ{player}! {score}.",
            "big_chance": "يا لها من فرصة! كان على {player} التسجيل.",
            "shot_on_target": "يا لها من تسديدة من {player}!",
            "red_card": "بطاقة حمراء! {team} بـ{players} لاعبين.",
            "yellow_card": "إنذار لـ{player}.",
            "momentum_swing": "{team} يسيطر الآن والجماهير تشعر بذلك.",
            "pressure_shift": "{team} يطارد الكرة في الأمام.",
            "chaos": "هجمة مقابل هجمة! كل شيء ممكن.",
            "control": "{team} يسيطر على الكرة والمباراة.",
            "sprint": "{player} يطير! {top_speed}!",
            "pass_of_match": "يا لها من تمريرة من {player}!",
            "milestone_distance": "{player} لا يتوقف عن الركض.",
            "milestone_passes": "كل شيء يمر عبر {player} اليوم.",
            "phase": "{ht_ft}: {home} {score} {away}.",
        },
    },
    "ja": {
        "states": {
            "opener": "先制！",
            "equaliser": "同点！",
            "go_ahead": "勝ち越し！",
            "extend_lead": "リードを広げる。",
            "pull_back": "1点返した！",
            "comeback": "逆転完了！",
            "late_winner": "終盤のドラマ！",
            "none": "",
        },
        "quality": {"high": "決めるべき決定機", "mid": "まずまずのチャンス", "low": "確率の低いシュート"},
        "outcome": {
            "saved": "GKがセーブ",
            "blocked": "ブロックされた",
            "off_target": "枠を外れた",
            "goal": "ゴール",
        },
        "verdict_for": "チャンスの質もスコアを裏付けている",
        "verdict_against": "スコアがチャンスの質を上回っている",
        "club_good": "{club}にとって朗報：",
        "club_bad": "{club}には不安材料：",
        "player_focus": "{focus}に注目：",
        "data": "データ",
        "head": {
            "goal": "{player}が{team}にゴール",
            "big_chance": "{player}に決定機",
            "shot_on_target": "{player}の強烈なシュート",
            "red_card": "{team}は{players}人に",
            "yellow_card": "{player}にイエローカード",
            "momentum_swing": "流れは{team}へ",
            "pressure_shift": "{team}がプレスを強める",
            "chaos": "試合がオープンに",
            "control": "{team}が主導権を握る",
            "sprint": "{player}がトップスピード",
            "pass_of_match": "今日のベストパス",
            "milestone_distance": "{player}が走行距離トップ",
            "milestone_passes": "{player}が試合を操る",
            "phase": "{ht_ft}：{home} {score} {away}",
        },
        "why": {
            "goal": "{state}{player}が{xg} xGのチャンス（{quality}）を時速{speed}のシュートで決めた。スコアは{score}、xGは{team} {xg_team}、{opp} {xg_opp}で、{verdict}。",
            "big_chance": "{player}は{dist}の位置から{xg} xGの決定機を得たが、{outcome}。このようなチャンスは100回中約{xg_pct}回決まるため、{team}には痛い場面だ。",
            "shot_on_target": "{player}が時速{speed}のシュートでGKを試す。この速さではGKが反応できる時間はほんの一瞬だ。",
            "red_card": "{team}は残り{minutes_left}を{players}人で戦う。直前の10分間のボール保持率は{poss}だったが、ここからは{opp}が主導権を握るだろう。",
            "yellow_card": "{player}に警告（{team}の警告数：{yellows}）。今後は守備で強く行きにくくなる。",
            "momentum_swing": "5分間で流れの指数が{mom_prev}から{mom_now}に変化。この時間帯の{team}の保持率は{poss}、シュートは{shots}本。",
            "pressure_shift": "{team}がより高い位置からプレス：PPDAは{ppda_prev}から{ppda_now}に低下し、{opp}はボールを失うまでのパス数が大きく減っている。",
            "chaos": "コントロール対カオス指数が{chaos_prev}から{chaos}に急上昇し、5分間でボールロストは{turnovers}回。どちらもボールを保持できず、ミスとゴールが生まれやすい時間帯だ。",
            "control": "{team}が試合を落ち着かせた：コントロール対カオス指数は{chaos}、直近5分の保持率{poss}、パス成功率{acc}。",
            "sprint": "{player}が{top_speed}を記録。このスピードがあると、DFは背後のスペースを守るためにラインを下げざるを得ない。",
            "pass_of_match": "{player}が難易度{diff}のパスを成功：{pdist}の距離、パスコースには相手{lane}人。{player_short}の今日のパス成功率は{acc}。",
            "milestone_distance": "{player}が今日最初に{km}を走破。{team}のボールを持たない時の運動量を示している。",
            "milestone_passes": "{player}はパス{passes}本、成功率{acc}。{team}の攻撃は彼を経由している。",
            "phase": "{ht_ft}：{home} {score} {away}。{home}の保持率{poss_home}、xGは{xg_home}対{xg_away}、シュートは{shots_home}対{shots_away}。",
        },
        "fan": {
            "goal": "{state}{player}のゴール！ {score}。",
            "big_chance": "惜しい！{player}は決めたかった。",
            "shot_on_target": "{player}の強烈な一撃！",
            "red_card": "レッドカード！{team}は{players}人に。",
            "yellow_card": "{player}にイエロー。",
            "momentum_swing": "今は{team}の時間帯、スタジアムも沸いている。",
            "pressure_shift": "{team}が高い位置でボールを狩る。",
            "chaos": "攻守が目まぐるしく入れ替わる！",
            "control": "{team}がボールと試合を支配。",
            "sprint": "{player}が飛ぶように走る！{top_speed}！",
            "pass_of_match": "{player}の見事なパス！",
            "milestone_distance": "{player}は走り続ける。",
            "milestone_passes": "今日の攻撃はすべて{player}から。",
            "phase": "{ht_ft}：{home} {score} {away}。",
        },
    },
}

HT_FT = {
    "en": ("Half time", "Full time"),
    "es": ("Descanso", "Final"),
    "fr": ("Mi-temps", "Fin du match"),
    "pt": ("Intervalo", "Fim de jogo"),
    "ar": ("نهاية الشوط الأول", "نهاية المباراة"),
    "ja": ("前半終了", "試合終了"),
}

FACT_LABELS: dict[str, dict[str, str]] = {
    "xg": {"en": "xG", "es": "xG", "fr": "xG", "pt": "xG", "ar": "xG", "ja": "xG"},
    "shot_speed": {
        "en": "Shot speed",
        "es": "Velocidad del tiro",
        "fr": "Vitesse de frappe",
        "pt": "Velocidade do chute",
        "ar": "سرعة التسديدة",
        "ja": "シュート速度",
    },
    "shot_distance": {
        "en": "Distance",
        "es": "Distancia",
        "fr": "Distance",
        "pt": "Distância",
        "ar": "المسافة",
        "ja": "距離",
    },
    "pass_difficulty": {
        "en": "Pass difficulty",
        "es": "Dificultad del pase",
        "fr": "Difficulté de la passe",
        "pt": "Dificuldade do passe",
        "ar": "صعوبة التمريرة",
        "ja": "パス難易度",
    },
    "pass_distance": {
        "en": "Pass distance",
        "es": "Distancia del pase",
        "fr": "Longueur de la passe",
        "pt": "Distância do passe",
        "ar": "مسافة التمريرة",
        "ja": "パス距離",
    },
    "pass_accuracy": {
        "en": "Pass accuracy",
        "es": "Acierto en el pase",
        "fr": "Passes réussies",
        "pt": "Acerto nos passes",
        "ar": "دقة التمرير",
        "ja": "パス成功率",
    },
    "top_speed": {
        "en": "Top speed",
        "es": "Velocidad máxima",
        "fr": "Vitesse de pointe",
        "pt": "Velocidade máxima",
        "ar": "السرعة القصوى",
        "ja": "最高速度",
    },
    "distance": {
        "en": "Distance covered",
        "es": "Distancia recorrida",
        "fr": "Distance parcourue",
        "pt": "Distância percorrida",
        "ar": "المسافة المقطوعة",
        "ja": "走行距離",
    },
    "ppda": {"en": "PPDA", "es": "PPDA", "fr": "PPDA", "pt": "PPDA", "ar": "PPDA", "ja": "PPDA"},
    "chaos_index": {
        "en": "Control vs Chaos",
        "es": "Control vs Caos",
        "fr": "Contrôle vs Chaos",
        "pt": "Controle vs Caos",
        "ar": "السيطرة مقابل الفوضى",
        "ja": "コントロール対カオス",
    },
    "momentum": {
        "en": "Momentum",
        "es": "Impulso",
        "fr": "Élan",
        "pt": "Momento",
        "ar": "الزخم",
        "ja": "流れ",
    },
    "possession_window": {
        "en": "Possession",
        "es": "Posesión",
        "fr": "Possession",
        "pt": "Posse",
        "ar": "الاستحواذ",
        "ja": "保持率",
    },
    "possession": {
        "en": "Possession",
        "es": "Posesión",
        "fr": "Possession",
        "pt": "Posse",
        "ar": "الاستحواذ",
        "ja": "保持率",
    },
    "xg_total": {
        "en": "Total xG",
        "es": "xG total",
        "fr": "xG total",
        "pt": "xG total",
        "ar": "مجموع xG",
        "ja": "合計xG",
    },
    "score": {
        "en": "Score",
        "es": "Marcador",
        "fr": "Score",
        "pt": "Placar",
        "ar": "النتيجة",
        "ja": "スコア",
    },
    "shots": {
        "en": "Shots",
        "es": "Tiros",
        "fr": "Tirs",
        "pt": "Finalizações",
        "ar": "التسديدات",
        "ja": "シュート",
    },
    "shots_window": {
        "en": "Shots",
        "es": "Tiros",
        "fr": "Tirs",
        "pt": "Finalizações",
        "ar": "التسديدات",
        "ja": "シュート",
    },
    "turnovers_window": {
        "en": "Turnovers",
        "es": "Pérdidas",
        "fr": "Pertes",
        "pt": "Perdas",
        "ar": "فقدان الكرة",
        "ja": "ボールロスト",
    },
    "passes": {
        "en": "Passes",
        "es": "Pases",
        "fr": "Passes",
        "pt": "Passes",
        "ar": "التمريرات",
        "ja": "パス",
    },
    "players_on_pitch": {
        "en": "Players",
        "es": "Jugadores",
        "fr": "Joueurs",
        "pt": "Jogadores",
        "ar": "اللاعبون",
        "ja": "人数",
    },
    "minutes_left": {
        "en": "Minutes left",
        "es": "Minutos restantes",
        "fr": "Minutes restantes",
        "pt": "Minutos restantes",
        "ar": "الدقائق المتبقية",
        "ja": "残り時間",
    },
    "player_goals": {
        "en": "Goals today",
        "es": "Goles hoy",
        "fr": "Buts aujourd'hui",
        "pt": "Gols hoje",
        "ar": "أهداف اليوم",
        "ja": "本日のゴール",
    },
    "opponents_bypassed": {
        "en": "Opponents in lane",
        "es": "Rivales en la línea",
        "fr": "Adversaires sur la trajectoire",
        "pt": "Adversários na linha",
        "ar": "منافسون في المسار",
        "ja": "コース上の相手",
    },
    "pass_accuracy_window": {
        "en": "Pass accuracy",
        "es": "Acierto en el pase",
        "fr": "Passes réussies",
        "pt": "Acerto nos passes",
        "ar": "دقة التمرير",
        "ja": "パス成功率",
    },
    "yellow_cards": {
        "en": "Yellow cards",
        "es": "Amarillas",
        "fr": "Cartons jaunes",
        "pt": "Amarelos",
        "ar": "البطاقات الصفراء",
        "ja": "イエローカード",
    },
}


MEMORY_LINE = {
    "en": "{player_short} now has {season_goals} league goals this season.",
    "es": "{player_short} suma {season_goals} goles de liga esta temporada.",
    "fr": "{player_short} compte désormais {season_goals} buts en championnat cette saison.",
    "pt": "{player_short} chega a {season_goals} gols na liga nesta temporada.",
    "ar": "رصيد {player_short} الآن {season_goals} أهداف في الدوري هذا الموسم.",
    "ja": "{player_short}は今季リーグ通算{season_goals}得点。",
}

# ----------------------------------------------------------------------------- rendering


@dataclass
class Rendered:
    headline: str
    text: str
    cited: list[str]


class _Binder:
    """Collects placeholder values and remembers which facts were used."""

    def __init__(self, lang: str) -> None:
        self.lang = lang
        self.values: dict[str, str] = {}
        self.sources: dict[str, str] = {}

    def num(
        self,
        key: str,
        fact: Fact | None,
        *,
        scale: float = 1.0,
        unit: str | None = None,
        digits: int | None = None,
    ) -> None:
        if fact is None or isinstance(fact.value, str) and scale != 1.0:
            return
        value = fact.value
        if not isinstance(value, str):
            value = value * scale
            if digits is not None:
                value = round(value, digits)
                if digits == 0:
                    value = int(value)
        u = fact.unit if unit is None else unit
        text = format_value(value, u, fact.kind if scale == 1.0 else "")
        if self.lang in COMMA_DECIMAL:
            text = text.replace(".", ",")
        self.values[key] = text
        self.sources[key] = fact.fact_id

    def text(self, key: str, value: str | None) -> None:
        if value is not None:
            self.values[key] = value

    def render(self, template: str) -> tuple[str, list[str]]:
        fields = [f for _, f, _, _ in string.Formatter().parse(template) if f]
        missing = [f for f in fields if f not in self.values]
        if missing:
            raise KeyError(f"missing placeholders: {missing}")
        out = template.format(**self.values)
        cited = sorted({self.sources[f] for f in fields if f in self.sources}, key=lambda x: int(x[1:]))
        return " ".join(out.split()), cited


def template_key(ctx: MomentContext) -> str:
    t = ctx.moment.type.value
    if t == "chaos_spike":
        return "chaos" if ctx.fact("turnovers_window") else "control"
    if t == "milestone":
        return "milestone_distance" if ctx.fact("distance") else "milestone_passes"
    return t


def _bind(ctx: MomentContext, lang: str, outcome: str | None) -> _Binder:
    L = T[lang]
    b = _Binder(lang)
    m = ctx.moment
    b.text("player", ctx.player)
    b.text("player_short", ctx.player_short)
    b.text("team", ctx.team)
    b.text("opp", ctx.opponent)
    b.text("home", ctx.home)
    b.text("away", ctx.away)
    b.text("state", L["states"].get(ctx.state, ""))
    xg = ctx.fact("xg")
    b.num("xg", xg)
    b.num("xg_pct", xg, scale=100, unit="", digits=0)
    if xg is not None:
        q = "high" if float(xg.value) >= 0.4 else "mid" if float(xg.value) >= 0.15 else "low"
        b.text("quality", L["quality"][q])
    b.num("speed", ctx.fact("shot_speed"))
    b.num("dist", ctx.fact("shot_distance"))
    b.text("outcome", L["outcome"].get(outcome or "", L["outcome"]["off_target"]))
    score = ctx.fact("score")
    if score:
        b.values["score"] = str(score.value)
        b.sources["score"] = score.fact_id
    xg_totals = [f for f in ctx.facts if f.kind == "xg_total"]
    if m.team and len(xg_totals) >= 2:
        mine = next((f for f in xg_totals if f.team == m.team), None)
        theirs = next((f for f in xg_totals if f.team != m.team), None)
        b.num("xg_team", mine)
        b.num("xg_opp", theirs)
        if mine and theirs:
            b.text(
                "verdict",
                L["verdict_for"] if float(mine.value) >= float(theirs.value) else L["verdict_against"],
            )
    if len(xg_totals) >= 2:
        b.num("xg_home", next((f for f in xg_totals if f.team == "home"), None))
        b.num("xg_away", next((f for f in xg_totals if f.team == "away"), None))
    shots = [f for f in ctx.facts if f.kind == "shots"]
    b.num("shots_home", next((f for f in shots if f.team == "home"), None))
    b.num("shots_away", next((f for f in shots if f.team == "away"), None))
    b.num("poss_home", ctx.fact("possession"))
    b.num("players", ctx.fact("players_on_pitch"))
    left = ctx.fact("minutes_left")
    if left is not None:
        b.num("minutes_left", left, unit="'" if lang in {"en"} else "")
        if lang != "en":
            suffix = {"es": " minutos", "fr": " minutes", "pt": " minutos", "ar": " دقيقة", "ja": "分"}[lang]
            b.values["minutes_left"] = b.values["minutes_left"] + suffix
    b.num("poss", ctx.fact("possession_window"))
    b.num("yellows", ctx.fact("yellow_cards"))
    moms = [f for f in ctx.facts if f.kind == "momentum"]
    if len(moms) >= 2:
        b.num("mom_prev", moms[0])
        b.num("mom_now", moms[1])
    b.num("shots", ctx.fact("shots_window"))
    ppda = [f for f in ctx.facts if f.kind == "ppda"]
    if len(ppda) >= 2:
        b.num("ppda_prev", ppda[0])
        b.num("ppda_now", ppda[1])
    chaos = [f for f in ctx.facts if f.kind == "chaos_index"]
    if chaos:
        b.num("chaos", chaos[0], unit="")
    if len(chaos) >= 2:
        b.num("chaos_prev", chaos[1], unit="")
    b.num("turnovers", ctx.fact("turnovers_window"))
    b.num("acc", ctx.fact("pass_accuracy_window") or ctx.fact("pass_accuracy"))
    b.num("top_speed", ctx.fact("top_speed"))
    b.num("km", ctx.fact("distance"))
    b.num("passes", ctx.fact("passes"))
    b.num("diff", ctx.fact("pass_difficulty"), unit="/100")
    b.num("pdist", ctx.fact("pass_distance"))
    b.num("lane", ctx.fact("opponents_bypassed"))
    if m.type.value == "phase":
        b.text("ht_ft", HT_FT[lang][0 if "Half" in m.title else 1])
    b.num("season_goals", ctx.fact("season_goals"))
    return b


def _with_memory(b: _Binder, lang: str, text: str, cited: list[str]) -> tuple[str, list[str]]:
    if "season_goals" in b.values and b.values.get("player_short"):
        extra, extra_cited = b.render(MEMORY_LINE[lang])
        return f"{text} {extra}", sorted(set(cited) | set(extra_cited), key=lambda x: int(x[1:]))
    return text, cited


def render_explanation(ctx: MomentContext, lang: str = "en", outcome: str | None = None) -> Rendered:
    lang = lang if lang in T else "en"
    key = template_key(ctx)
    b = _bind(ctx, lang, outcome)
    head, _ = b.render(T[lang]["head"][key])
    text, cited = b.render(T[lang]["why"][key])
    text, cited = _with_memory(b, lang, text, cited)
    return Rendered(head, text, cited)


def render_personalized(
    ctx: MomentContext,
    mode: Mode,
    lang: str,
    *,
    club: Side | None = None,
    focus_player_id: str | None = None,
    focus_player_name: str | None = None,
    outcome: str | None = None,
) -> Rendered:
    lang = lang if lang in T else "en"
    L = T[lang]
    key = template_key(ctx)
    b = _bind(ctx, lang, outcome)
    head, _ = b.render(L["head"][key])
    why, why_cited = b.render(L["why"][key])
    why, why_cited = _with_memory(b, lang, why, why_cited)
    fan, fan_cited = b.render(L["fan"][key])
    if mode == "analyst":
        data = [f for f in ctx.moment.facts if f.kind in FACT_LABELS][:4]
        parts = []
        for f in data:
            val = f.display()
            if lang in COMMA_DECIMAL:
                val = val.replace(".", ",")
            parts.append(f"{FACT_LABELS[f.kind].get(lang, f.label)} {val}")
        tail = f" {L['data']}: " + " · ".join(parts) if parts else ""
        cited = sorted(set(why_cited) | {f.fact_id for f in data}, key=lambda x: int(x[1:]))
        return Rendered(head, why + tail, cited)
    if mode == "club":
        rel = ctx.side_relation(club)
        if rel != "neutral" and club is not None:
            club_name = ctx.home if club == "home" else ctx.away
            prefix = L["club_good" if rel == "good" else "club_bad"].format(club=club_name)
            return Rendered(head, prefix + why, why_cited)
        return Rendered(head, fan, fan_cited)
    if mode == "player":
        if focus_player_id and ctx.moment.player_id == focus_player_id:
            prefix = L["player_focus"].format(focus=focus_player_name or ctx.player or "")
            return Rendered(head, prefix + why, why_cited)
        return Rendered(head, fan, fan_cited)
    return Rendered(head, fan, fan_cited)


def render_commentary(
    ctx: MomentContext, lang: str = "en", outcome: str | None = None, seed: int = 0
) -> tuple[str, str]:
    lang = lang if lang in T else "en"
    key = template_key(ctx)
    b = _bind(ctx, lang, outcome)
    text, _ = b.render(T[lang]["fan"][key])
    tone = {
        "goal": "excited",
        "red_card": "excited",
        "big_chance": "build",
        "momentum_swing": "build",
        "chaos": "build",
        "phase": "calm",
    }.get(key, "calm")
    if key == "goal" and ctx.state in {"pull_back"}:
        tone = "build"
    rnd = random.Random(seed)
    prefix = f"{ctx.moment.minute}' "
    if lang == "en" and key in {"goal", "big_chance"} and rnd.random() < 0.5:
        prefix += rnd.choice(["Oh my! ", "Here it is! ", "Look at this! "])
    return prefix + text, tone
