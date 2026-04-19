import os
import requests
from datetime import datetime
import gradio as gr
from groq import Groq

# ── Secrets ───────────────────────────────────────────────────────────────────
OPENWEATHER_KEY = os.environ.get("OPENWEATHER_KEY")
GROQ_API_KEY    = os.environ.get("GROQ_API_KEY")

CITY    = "Bahawalnagar"
COUNTRY = "PK"

groq_client = Groq(api_key=GROQ_API_KEY)


# ══════════════════════════════════════════════════════════════════════════════
# WEATHER DATA FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def get_coords():
    geo = requests.get(
        f"https://api.openweathermap.org/geo/1.0/direct?q={CITY},{COUNTRY}&limit=1&appid={OPENWEATHER_KEY}"
    ).json()
    return (geo[0]["lat"], geo[0]["lon"]) if geo else (29.9833, 73.2500)

def get_current_weather():
    url = f"https://api.openweathermap.org/data/2.5/weather?q={CITY},{COUNTRY}&appid={OPENWEATHER_KEY}&units=metric"
    r = requests.get(url)
    if r.status_code != 200:
        return None, f"Error: {r.text}"
    d = r.json()
    return {
        "temp":        round(d["main"]["temp"], 1),
        "feels_like":  round(d["main"]["feels_like"], 1),
        "humidity":    d["main"]["humidity"],
        "wind_speed":  round(d["wind"]["speed"] * 3.6, 1),
        "description": d["weather"][0]["description"].capitalize(),
        "visibility":  d.get("visibility", 10000) // 1000,
        "pressure":    d["main"]["pressure"],
        "uvi":         0,  # requires OneCall — estimated below
        "clouds":      d["clouds"]["alc"] if "alc" in d.get("clouds", {}) else d["clouds"].get("all", 0),
    }, None

def get_forecast():
    url = f"https://api.openweathermap.org/data/2.5/forecast?q={CITY},{COUNTRY}&appid={OPENWEATHER_KEY}&units=metric&cnt=40"
    r = requests.get(url)
    if r.status_code != 200:
        return None, f"Error: {r.text}"
    items = r.json()["list"]
    days = {}
    for item in items:
        date = item["dt_txt"].split(" ")[0]
        if date not in days:
            days[date] = {"temps": [], "desc": item["weather"][0]["description"],
                          "rain": 0, "humidity": [], "wind": []}
        days[date]["temps"].append(item["main"]["temp"])
        days[date]["humidity"].append(item["main"]["humidity"])
        days[date]["wind"].append(item["wind"]["speed"] * 3.6)
        days[date]["rain"] += item.get("rain", {}).get("3h", 0)
    result = []
    for date, v in list(days.items())[:7]:
        result.append({
            "date":     datetime.strptime(date, "%Y-%m-%d").strftime("%a %d %b"),
            "date_raw": date,
            "high":     round(max(v["temps"]), 1),
            "low":      round(min(v["temps"]), 1),
            "desc":     v["desc"].capitalize(),
            "rain":     round(v["rain"], 1),
            "humidity": round(sum(v["humidity"]) / len(v["humidity"])),
            "wind":     round(sum(v["wind"]) / len(v["wind"]), 1),
        })
    return result, None

def get_air_quality():
    lat, lon = get_coords()
    d = requests.get(
        f"https://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={OPENWEATHER_KEY}"
    ).json()
    aqi  = d["list"][0]["main"]["aqi"]
    comp = d["list"][0]["components"]
    return {
        "aqi":   aqi,
        "label": {1:"Good", 2:"Fair", 3:"Moderate", 4:"Poor", 5:"Very Poor"}[aqi],
        "pm2_5": round(comp["pm2_5"], 1),
        "pm10":  round(comp["pm10"], 1),
        "co":    round(comp["co"], 1),
        "no2":   round(comp["no2"], 1),
    }, None


# ══════════════════════════════════════════════════════════════════════════════
# CALCULATION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def heat_index(temp_c, humidity):
    """Steadman heat index in Celsius."""
    t = temp_c * 9/5 + 32  # to Fahrenheit
    rh = humidity
    hi = (-42.379 + 2.04901523*t + 10.14333127*rh
          - 0.22475541*t*rh - 0.00683783*t*t
          - 0.05481717*rh*rh + 0.00122874*t*t*rh
          + 0.00085282*t*rh*rh - 0.00000199*t*t*rh*rh)
    return round((hi - 32) * 5/9, 1)

def thi_index(temp_c, humidity):
    """Temperature-Humidity Index for livestock."""
    return round((1.8 * temp_c + 32) - ((0.55 - 0.0055 * humidity) * ((1.8 * temp_c + 32) - 58)), 1)

def work_safety_score(temp_c, humidity, wind_kmh):
    hi = heat_index(temp_c, humidity)
    if hi < 27:   return "🟢 Safe",    "Normal outdoor work is fine."
    elif hi < 32: return "🟡 Caution", "Take breaks every 30 mins, drink water."
    elif hi < 41: return "🟠 Warning", "Limit heavy outdoor work. Rest in shade."
    else:         return "🔴 Danger",  "Avoid outdoor work. Risk of heatstroke."

def fog_risk(visibility_km, humidity, temp_c):
    if visibility_km <= 1 and humidity >= 90:
        return "🌫️ Dense Fog", "Extremely dangerous. Avoid driving. Turn on fog lights."
    elif visibility_km <= 3 and humidity >= 80:
        return "🌫️ Moderate Fog", "Drive slowly. Use fog lights. Allow extra travel time."
    elif temp_c < 10 and humidity >= 75:
        return "⚠️ Fog Likely Tonight", "Fog may form after midnight. Check before early morning travel."
    else:
        return "✅ No Fog Risk", "Visibility is clear."

def flood_risk(rain_mm_24h, wind_kmh):
    if rain_mm_24h > 80:
        return "🔴 High Flood Risk", "Extreme rainfall. Stay away from Sutlej River banks and low areas."
    elif rain_mm_24h > 40:
        return "🟠 Moderate Risk",   "Heavy rain. Monitor local canals. Avoid low-lying fields."
    elif rain_mm_24h > 15:
        return "🟡 Low Risk",        "Significant rain expected. Check drainage on your land."
    else:
        return "🟢 No Flood Risk",   "Rainfall is within normal range."

def school_safety(temp_c, humidity, aqi_level):
    hi = heat_index(temp_c, humidity)
    if aqi_level >= 4:
        return "🔴 Not Safe", "Air quality is poor. Keep children indoors."
    elif hi >= 41:
        return "🔴 Not Safe", "Dangerous heat. Cancel outdoor activities."
    elif hi >= 35 or aqi_level == 3:
        return "🟠 Caution", "Limit outdoor play to 15 mins. Keep kids hydrated."
    else:
        return "🟢 Safe", "Safe for normal outdoor school activities."

def livestock_thi(temp_c, humidity):
    thi = thi_index(temp_c, humidity)
    if thi < 72:   return "🟢 No Stress",     f"THI {thi} — Normal. Animals are comfortable."
    elif thi < 79: return "🟡 Mild Stress",   f"THI {thi} — Increase water supply. Add shade."
    elif thi < 89: return "🟠 Moderate",      f"THI {thi} — Use fans/sprinklers. Reduce feeding in heat."
    else:          return "🔴 Severe Stress",  f"THI {thi} — Emergency cooling needed. Risk of death."

def pest_risk(temp_c, humidity, rain_mm):
    risks = []
    if temp_c > 28 and humidity > 70:
        risks.append("Cotton whitefly risk HIGH — spray neem oil early morning")
    if humidity > 80 and rain_mm > 10:
        risks.append("Fungal blight risk HIGH — apply fungicide within 24 hours")
    if temp_c > 32 and humidity < 40:
        risks.append("Aphid outbreak likely — inspect crop undersides")
    if temp_c > 25 and rain_mm > 20:
        risks.append("Armyworm risk after rain — check fields at night")
    return risks if risks else ["No significant pest risks today — conditions are normal"]

def get_season_advice():
    month = datetime.now().month
    if month in [11, 12, 1, 2, 3, 4]:
        return "rabi", "wheat", "Wheat season (Rabi). Key tasks: irrigation timing, frost protection, fertiliser application."
    elif month in [5, 6, 7, 8, 9, 10]:
        return "kharif", "cotton", "Kharif season. Key crops: cotton, sugarcane. Watch for heat stress and pest attacks."

def crop_calendar_advice(forecast):
    season, crop, desc = get_season_advice()
    hot_days  = sum(1 for d in forecast if d["high"] > 40)
    rain_days = sum(1 for d in forecast if d["rain"] > 5)
    cold_days = sum(1 for d in forecast if d["low"] < 5)
    tips = [f"**Season:** {desc}"]
    if hot_days >= 3:
        tips.append(f"⚠️ {hot_days} days above 40°C this week — irrigate {crop} in early morning (5–7am)")
    if rain_days >= 2:
        tips.append(f"🌧️ {rain_days} rainy days — delay fertiliser spray until after rain")
    if cold_days >= 1:
        tips.append(f"❄️ {cold_days} cold nights below 5°C — risk of frost damage to young wheat")
    if not hot_days and not rain_days and not cold_days:
        tips.append(f"✅ Good week for field work. Ideal conditions for {crop}.")
    return "\n\n".join(tips)


# ══════════════════════════════════════════════════════════════════════════════
# GROQ AI FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def ask_advisor(question, context=""):
    system = f"""You are a helpful local weather advisor for Bahawalnagar, Punjab, Pakistan.
You deeply understand local issues: extreme summer heat (45°C+), dust storms (aandhi),
dense winter fog, cotton/wheat/sugarcane farming, Sutlej River flooding, irrigation timing,
livestock dairy farming, and daily life in this region.
Current weather context: {context}
Give practical, friendly advice in 3-5 sentences.
If asked in Urdu or Punjabi, reply in that language."""
    resp = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role":"system","content":system},{"role":"user","content":question}],
        max_tokens=350, temperature=0.7,
    )
    return resp.choices[0].message.content

def generate_urdu_digest(weather, forecast, aqi):
    prompt = f"""
Current weather in Bahawalnagar: Temp {weather['temp']}°C, Humidity {weather['humidity']}%,
Wind {weather['wind_speed']} km/h, Condition: {weather['description']}.
7-day forecast: {[f"{d['date']}: High {d['high']}°C, Rain {d['rain']}mm" for d in forecast[:5]]}
Air quality: {aqi['label']}
Write a weekly weather summary in URDU for the farmers and general public of Bahawalnagar.
Include: this week's main weather pattern, any risks (heat, rain, fog), and 2-3 practical tips.
Keep it friendly, simple, and about 100 words. Use easy Urdu that uneducated farmers can understand.
"""
    return ask_advisor(prompt)


# ══════════════════════════════════════════════════════════════════════════════
# FORMATTING HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def fmt_current(w):
    if not w: return "❌ Weather data unavailable."
    icon = ("☀️" if "clear" in w["description"].lower() else
            "⛅" if "cloud" in w["description"].lower() else
            "🌧️" if "rain"  in w["description"].lower() else
            "🌫️" if "fog"   in w["description"].lower() else "🌤️")
    hi, hi_msg = work_safety_score(w["temp"], w["humidity"], w["wind_speed"])
    fog_status, fog_msg = fog_risk(w["visibility"], w["humidity"], w["temp"])
    return f"""## {icon} Bahawalnagar — Live Weather
| Detail | Value |
|---|---|
| **Condition** | {w['description']} |
| **Temperature** | {w['temp']}°C (feels like {w['feels_like']}°C) |
| **Humidity** | {w['humidity']}% |
| **Wind** | {w['wind_speed']} km/h |
| **Visibility** | {w['visibility']} km |
| **Pressure** | {w['pressure']} hPa |
### Outdoor Safety
**{hi}** — {hi_msg}
### Fog Status
**{fog_status}** — {fog_msg}
"""

def fmt_forecast(days):
    if not days: return "❌ Forecast unavailable."
    lines = ["## 📅 7-Day Forecast\n",
             "| Day | High | Low | Condition | Rain | Humidity |",
             "|---|---|---|---|---|---|"]
    for d in days:
        lines.append(f"| {d['date']} | {d['high']}°C | {d['low']}°C | {d['desc']} | {d['rain']} mm | {d['humidity']}% |")
    return "\n".join(lines)

def fmt_aqi(aq):
    if not aq: return "❌ Air quality unavailable."
    e = {1:"🟢",2:"🟡",3:"🟠",4:"🔴",5:"🟣"}.get(aq["aqi"],"⚪")
    health = {
        1: "Air is clean. Safe for everyone.",
        2: "Acceptable quality. Sensitive people should limit prolonged outdoor exposure.",
        3: "Moderate pollution. Elderly and children should reduce outdoor time.",
        4: "Poor air. Everyone should reduce outdoor activity.",
        5: "Very poor. Stay indoors. Wear mask if going outside.",
    }
    return f"""## 🌬️ Air Quality Index
{e} **{aq['label']}** (Level {aq['aqi']}/5)
{health[aq['aqi']]}
| Pollutant | Value | Safe Limit |
|---|---|---|
| PM2.5 | {aq['pm2_5']} µg/m³ | < 25 µg/m³ |
| PM10  | {aq['pm10']} µg/m³  | < 50 µg/m³ |
| CO    | {aq['co']} µg/m³   | < 4000 µg/m³ |
| NO2   | {aq['no2']} µg/m³  | < 40 µg/m³ |
"""

def fmt_crop_calendar(forecast):
    if not forecast: return "❌ Forecast data needed."
    _, crop, season_desc = get_season_advice()
    month_name = datetime.now().strftime("%B")
    calendar = {
        "wheat": {
            "Nov": "Sow wheat (Nov 1–20 is ideal window)",
            "Dec": "First irrigation 20–25 days after sowing",
            "Jan": "Second irrigation + urea top-dressing",
            "Feb": "Watch for yellow rust disease in cool humid weather",
            "Mar": "Third irrigation. Grain filling stage — critical",
            "Apr": "Harvest when crop turns golden. Avoid rain delay",
        },
        "cotton": {
            "May": "Prepare land. Pre-sowing irrigation",
            "Jun": "Sow cotton (June 1–15). Monitor germination",
            "Jul": "First picking preparation. Spray for whitefly",
            "Aug": "Peak picking season. Watch for bollworm",
            "Sep": "Continue picking. Reduce irrigation",
            "Oct": "Final harvest. Prepare land for wheat",
        }
    }
    this_month_tip = calendar.get(crop, {}).get(month_name[:3], "Monitor crop regularly this month.")
    cal_str = fmt_forecast(forecast)
    ai_tips = crop_calendar_advice(forecast)
    return f"""## 🌾 Crop Calendar — {month_name}
**{season_desc}**
### This Month's Key Task
📌 {this_month_tip}
### AI Weather Analysis for Your Crops
{ai_tips}
### Weekly Forecast for Planning
{cal_str}
"""

def fmt_irrigation(weather, forecast):
    if not weather: return "❌ No data."
    temp, hum, wind = weather["temp"], weather["humidity"], weather["wind_speed"]
    et0 = round(0.0023 * (temp + 17.8) * (max(forecast[0]["high"] - forecast[0]["low"], 1) ** 0.5) * 1.2, 1) if forecast else 4.5
    rain_tomorrow = forecast[1]["rain"] if len(forecast) > 1 else 0
    if rain_tomorrow > 10:
        advice = f"⏸️ **Skip irrigation tomorrow** — {rain_tomorrow}mm rain expected. Save water."
    elif temp > 38:
        advice = f"💧 **Irrigate early morning (5–6am)** — High evaporation today. Night irrigation also acceptable."
    elif hum > 75:
        advice = f"✅ **Light irrigation only** — High humidity means less water stress on crop."
    else:
        advice = f"💧 **Normal irrigation recommended** — Apply {et0} mm of water."
    return f"""## 💧 Smart Irrigation Advisor
{advice}
| Factor | Value | Impact |
|---|---|---|
| Temperature | {temp}°C | {'High evaporation' if temp > 35 else 'Normal'} |
| Humidity | {hum}% | {'Less water needed' if hum > 70 else 'Normal demand'} |
| Wind | {wind} km/h | {'High drift — avoid sprinkler' if wind > 20 else 'Suitable for any method'} |
| Rain tomorrow | {rain_tomorrow} mm | {'Skip irrigation' if rain_tomorrow > 10 else 'Irrigation needed'} |
| Est. water need (ET0) | {et0} mm | Daily crop water requirement |
### Irrigation Methods for Bahawalnagar
- **Canal water available?** Flood irrigate in cool hours
- **Tubewell?** Use at night to reduce evaporation losses
- **Cotton at flowering?** Never skip irrigation at this stage
"""

def fmt_pest(weather, forecast):
    if not weather: return "❌ No data."
    risks = pest_risk(weather["temp"], weather["humidity"], forecast[0]["rain"] if forecast else 0)
    lines = ["## 🐛 Pest & Disease Risk Forecast\n"]
    for r in risks:
        lines.append(f"- {r}")
    lines.append(f"\n### Conditions Today\n- Temp: {weather['temp']}°C | Humidity: {weather['humidity']}% | Rain: {forecast[0]['rain'] if forecast else 0}mm")
    lines.append("\n### General Advice")
    lines.append("- Spray pesticides early morning or after sunset — never in midday heat")
    lines.append("- After heavy rain, re-apply fungicide within 24 hours")
    lines.append("- Check field edges first — pest attacks usually start from borders")
    return "\n".join(lines)

def fmt_flood(forecast):
    if not forecast: return "❌ No data."
    total_rain_3days = sum(d["rain"] for d in forecast[:3])
    risk_label, risk_msg = flood_risk(total_rain_3days, forecast[0]["wind"])
    return f"""## 🌊 Monsoon & Flood Risk Tracker
**{risk_label}**
{risk_msg}
| Period | Expected Rain | Risk |
|---|---|---|
| Next 24 hours | {forecast[0]['rain']} mm | {'High' if forecast[0]['rain']>30 else 'Low'} |
| Next 3 days   | {total_rain_3days} mm | {'High' if total_rain_3days>80 else 'Moderate' if total_rain_3days>40 else 'Low'} |
### If Flood Risk is High
- Move livestock to higher ground immediately
- Do not cross flooded roads or canals
- Contact Sutlej River Flood Control: 1122 (Rescue)
- Store 3 days of food, water, and medicines
"""

def fmt_school(weather, aqi):
    if not weather or not aqi: return "❌ No data."
    status, msg = school_safety(weather["temp"], weather["humidity"], aqi["aqi"])
    hi = heat_index(weather["temp"], weather["humidity"])
    return f"""## 🏫 School Day Safety Checker
**{status}**
{msg}
| Factor | Value | Status |
|---|---|---|
| Heat Index | {hi}°C | {'Dangerous' if hi>=41 else 'High' if hi>=35 else 'Normal'} |
| Air Quality | {aqi['label']} | {'Poor' if aqi['aqi']>=4 else 'Acceptable'} |
| Temperature | {weather['temp']}°C | {'Too hot' if weather['temp']>42 else 'OK'} |
### Tips for Parents & Teachers
- Schedule outdoor assembly before 8am or after 5pm
- Keep ORS (oral rehydration salts) available
- Watch for signs of heat exhaustion: dizziness, nausea, red skin
"""

def fmt_livestock(weather):
    if not weather: return "❌ No data."
    status, thi_msg = livestock_thi(weather["temp"], weather["humidity"])
    thi = thi_index(weather["temp"], weather["humidity"])
    return f"""## 🐄 Livestock Heat Stress Monitor
**{status}**
{thi_msg}
| Metric | Value |
|---|---|
| Temperature | {weather['temp']}°C |
| Humidity | {weather['humidity']}% |
| THI Index | {thi} |
### THI Scale Reference
| THI | Stress Level | Action |
|---|---|---|
| < 72 | None | Normal management |
| 72–78 | Mild | More water, shade |
| 79–88 | Moderate | Fans + sprinklers |
| > 89 | Severe | Emergency cooling |
### Immediate Actions When THI > 79
- Provide unlimited cold drinking water
- Run fans or sprinklers in animal sheds
- Reduce concentrate feed in afternoon
- Milk cows in early morning when cooler
- Contact vet if animal shows laboured breathing
"""


# ══════════════════════════════════════════════════════════════════════════════
# MASTER REFRESH
# ══════════════════════════════════════════════════════════════════════════════

def refresh_all():
    w,  _ = get_current_weather()
    f,  _ = get_forecast()
    aq, _ = get_air_quality()
    ctx   = str(w) if w else "No data"

    heat_advice = ask_advisor(
        f"Temp {w['temp']}°C, humidity {w['humidity']}%, wind {w['wind_speed']} km/h. "
        f"Assess heat and dust storm risk. Give safety advice for outdoor workers.",
        ctx) if w else "No data"

    farming_advice = ask_advisor(
        f"Weather: {ctx}. 3-day rain: {sum(d['rain'] for d in f[:3]) if f else 0}mm. "
        f"Give farming advice for cotton/wheat/sugarcane in Bahawalnagar.",
        ctx) if w else "No data"

    urdu = generate_urdu_digest(w, f, aq) if w and f and aq else "ڈیٹا دستیاب نہیں۔"

    return (
        fmt_current(w),
        fmt_forecast(f),
        fmt_aqi(aq),
        fmt_crop_calendar(f),
        fmt_irrigation(w, f),
        fmt_pest(w, f),
        fmt_flood(f),
        f"## 🌡️ Heat & Dust Alert\n\n{heat_advice}\n\n## 🌾 General Farming\n\n{farming_advice}",
        fmt_school(w, aq),
        fmt_livestock(w),
        f"## 🇵🇰 ہفتہ وار موسمی خلاصہ\n\n{urdu}",
    )

def chat(question, history):
    w, _ = get_current_weather()
    answer = ask_advisor(question, str(w) if w else "No data")
    history.append((question, answer))
    return "", history


# ══════════════════════════════════════════════════════════════════════════════
# GRADIO UI
# ══════════════════════════════════════════════════════════════════════════════

with gr.Blocks(title="Bahawalnagar Weather", theme=gr.themes.Soft()) as demo:
    gr.Markdown("""
# 🌤️ بہاولنگر موسمی ایپ — Bahawalnagar Weather App
**Live weather · AI farming · Flood alerts · Livestock · School safety · اردو خلاصہ**
""")

    refresh_btn = gr.Button("🔄 تازہ کریں — Refresh All Data", variant="primary", size="lg")

    with gr.Tabs():
        with gr.Tab("🌡️ Current Weather"):
            cur = gr.Markdown()

        with gr.Tab("📅 7-Day Forecast"):
            fore = gr.Markdown()

        with gr.Tab("🌬️ Air Quality"):
            aqi_out = gr.Markdown()

        with gr.Tab("🌾 Crop Calendar"):
            crop = gr.Markdown()

        with gr.Tab("💧 Irrigation Advisor"):
            irr = gr.Markdown()

        with gr.Tab("🐛 Pest & Disease"):
            pest = gr.Markdown()

        with gr.Tab("🌊 Flood Tracker"):
            flood = gr.Markdown()

        with gr.Tab("⚠️ Heat & Farm Alerts"):
            heat = gr.Markdown()

        with gr.Tab("🏫 School Safety"):
            school = gr.Markdown()

        with gr.Tab("🐄 Livestock (THI)"):
            live = gr.Markdown()

        with gr.Tab("🇵🇰 اردو خلاصہ"):
            urdu = gr.Markdown()

        with gr.Tab("🤖 AI Advisor"):
            gr.Markdown("### موسمی مشیر سے پوچھیں — Ask the AI Weather Advisor")
            bot = gr.Chatbot(height=380)
            with gr.Row():
                inp = gr.Textbox(
                    placeholder="e.g. کیا آج کپاس کو پانی دینا چاہیے؟ / Is it safe to spray pesticide today?",
                    scale=5, show_label=False
                )
                gr.Button("بھیجیں ↗", scale=1).click(chat, [inp, bot], [inp, bot])
            inp.submit(chat, [inp, bot], [inp, bot])
            gr.Examples(
                examples=[
                    "Is it safe to work in the fields today?",
                    "کیا آج آندھی آنے کا خطرہ ہے؟",
                    "When should I irrigate my cotton crop this week?",
                    "میری گائے بہت گرمی میں ہے، کیا کروں؟",
                    "Is fog expected tomorrow morning?",
                    "کیا گندم کے لیے یہ ہفتہ اچھا ہے؟",
                ],
                inputs=inp,
            )

    all_outputs = [cur, fore, aqi_out, crop, irr, pest, flood, heat, school, live, urdu]
    refresh_btn.click(refresh_all, outputs=all_outputs)
    demo.load(refresh_all, outputs=all_outputs)

demo.launch()
