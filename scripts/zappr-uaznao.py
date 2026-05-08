#!/usr/bin/env python3
import requests
import base64
import json
import re
import urllib.parse
import os
import xml.etree.ElementTree as ET

CATEGORY_KEYWORDS = {
    "Rai": ["rai"],
    "Mediaset": ["twenty seven", "twentyseven", "mediaset", "italia 1", "italia 2", "canale 5", "la 5", "cine 34", "top crime", "iris", "focus", "rete 4"],
    "Sport": ["inter", "milan", "lazio", "calcio", "tennis", "sport", "sportitalia", "trsport", "sports", "super tennis", "supertennis", "dazn", "eurosport", "sky sport", "rai sport", "eventi"],
    "Film - Serie TV": ["crime", "primafila", "cinema", "movie", "film", "serie", "hbo", "fox", "rakuten", "atlantic"],
    "News": ["news", "tg", "rai news", "sky tg", "tgcom", "euronews"],
    "Bambini": ["frisbee", "super!", "fresbee", "k2", "cartoon", "boing", "nick", "disney", "baby", "rai yoyo", "cartoonito", "kids"],
    "Documentari": ["documentaries", "discovery", "geo", "history", "nat geo", "nature", "arte", "documentary"],
    "Musica": ["deejay", "rds", "hits", "rtl", "mtv", "vh1", "radio", "music", "kiss", "kisskiss", "m2o", "fm", "r101", "rai radio"],
    "Altro": []
}

def get_category(name):
    n = name.lower()
    for cat, kws in CATEGORY_KEYWORDS.items():
        for kw in kws:
            if kw in n:
                return cat
    return "Altro"

def is_italian_channel(name):
    n = name.lower()
    paesi_stranieri = ["[inglese]", "[hr]", "[nl]", "[pl]", "[cz]", "[de]", "[fr]", "[es]", "[pt]"]
    return not any(paese in n for paese in paesi_stranieri)

def remove_ck_param(url):
    parsed = urllib.parse.urlparse(url)
    query_params = urllib.parse.parse_qs(parsed.query)
    if 'ck' in query_params:
        del query_params['ck']
        new_query = urllib.parse.urlencode(query_params, doseq=True)
        clean_url = parsed._replace(query=new_query).geturl()
        return clean_url
    return url

def normalize_name(name):
    """Normalizza il nome per il confronto con l'EPG."""
    if not name: return ""
    n = name.lower()
    n = re.sub(r"\s+", "", n)
    n = re.sub(r"\[.*?\]", "", n) # Rimuove tag come [UAZNAO] o [inglese]
    n = re.sub(r"\(.*?\)", "", n) # Rimuove parentesi
    n = re.sub(r"\.it\b", "", n)
    n = re.sub(r"hd|fullhd", "", n, flags=re.IGNORECASE)
    # Rimuove tutto ciò che non è alfanumerico per un confronto più robusto
    n = re.sub(r'[^a-z0-9À-ÿ]', '', n)
    return n

def create_tvg_map(epg_file="epg.xml"):
    """Legge un file EPG XML e mappa i nomi ai loro tvg-id e loghi."""
    tvg_map = {}
    if not os.path.exists(epg_file):
        print(f"⚠️ {epg_file} non trovato.")
        return tvg_map
        
    try:
        tree = ET.parse(epg_file)
        root = tree.getroot()
        for channel in root.findall('.//channel'):
            tvg_id = channel.get('id')
            name_elem = channel.find('display-name')
            icon_elem = channel.find('icon')
            
            if tvg_id and name_elem is not None:
                name = name_elem.text
                if name:
                    norm = normalize_name(name)
                    logo_url = icon_elem.get('src') if icon_elem is not None else ""
                    tvg_map[norm] = {"id": tvg_id, "logo": logo_url}
    except Exception as e:
        print(f"❌ Errore EPG: {e}")
    return tvg_map

def get_channel_info(name, tvg_map):
    """Restituisce (tvg_id, logo) per il canale cercandolo nell'EPG."""
    norm = normalize_name(name)
    epg_data = tvg_map.get(norm)
    
    tvg_id = epg_data["id"] if epg_data else norm
    logo = epg_data["logo"] if epg_data else ""
    
    return tvg_id, logo

def extinf_line(tvg_id, logo, group, name):
    # virgola subito dopo group-title, nessun spazio prima del nome
    logo = logo or ""
    return f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{logo}" group-title="{group}",{name}'

m3u_content = ["#EXTM3U"]
contatore_uaznao = 0
contatore_zappr = 0

# Carica il mapping tvg-id e loghi da epg.xml
tvg_map = create_tvg_map("epg.xml")

print("📡 Fetch Uaznao...")
try:
    url_uaznao = os.getenv("UAZNAO_URL")
    response = requests.get(url_uaznao, timeout=10)
    data = response.json()
    
    for item in data:
        if not is_italian_channel(item["channelName"]):
            continue
            
        category = get_category(item["channelName"])
        if '.mpd' in item['url'].lower():
            ck_match = re.search(r'ck=([^&\s]+)', item['url'])
            clearkey = ""
            if ck_match:
                ck_b64 = ck_match.group(1)
                try:
                    clearkey = base64.b64decode(ck_b64).decode('utf-8')
                except:
                    clearkey = ck_b64
            
            clean_url = remove_ck_param(item['url'])
            
            tvg_id, logo = get_channel_info(item["channelName"], tvg_map)
            m3u_content.append(
                extinf_line(
                    tvg_id,
                    logo,
                    category,
                    f'{item["channelName"]} [UAZNAO]'
                )
            )
            m3u_content.extend([
                '#KODIPROP:inputstream.adaptive.license_type=org.w3.clearkey',
                f'#KODIPROP:inputstream.adaptive.license_key={clearkey}',
                clean_url
            ])
            contatore_uaznao += 1
            print(f"✓ UAZNAO {item['channelName']} → {category}")
except Exception as e:
    print(f"❌ Uaznao error: {e}")

print("\n📡 Fetch Zappr...")
try:
    url_zappr = "https://channels.zappr.stream/it/dtt/national.json"
    response = requests.get(url_zappr, timeout=10)
    data = response.json()
    
    for channel in data["channels"]:
        name = channel["name"]
        lcn = channel.get("lcn", "")
        logo = f"https://channels.zappr.stream/logos/it/optimized/{channel.get('logo', '')}" if channel.get('logo') else ""
        category = get_category(name)
        
        url_to_use = None
        
        if "geoblock" in channel and isinstance(channel["geoblock"], dict) and "url" in channel["geoblock"]:
            geoblock_url = channel["geoblock"]["url"]
            if geoblock_url and geoblock_url != "True" and "zappr://" not in geoblock_url:
                url_to_use = geoblock_url
                print(f"✓ ZAPPR GEO {name} → {category}")
        
        if url_to_use is None:
            main_url = channel.get("url", "")
            if main_url and "zappr://" not in main_url:
                url_to_use = main_url
                print(f"✓ ZAPPR MAIN {name} → {category}")
        
        if url_to_use:
            tvg_id, epg_logo = get_channel_info(name, tvg_map)
            # Usa il logo dell'API se presente, altrimenti quello dell'EPG/Hardcoded
            logo_final = logo if logo else epg_logo
            m3u_content.append(
                extinf_line(
                    tvg_id,
                    logo_final,
                    category,
                    f'{name} [ZAPPR]'
                )
            )
            m3u_content.append(url_to_use)
            contatore_zappr += 1
except Exception as e:
    print(f"❌ Zappr error: {e}")

print(f"\n📊 RISULTATO:")
print(f"   Uaznao MPD DRM: {contatore_uaznao} canali")
print(f"   Zappr: {contatore_zappr} canali")
print(f"   TOTALE: {contatore_uaznao + contatore_zappr} canali")

output_file = "zappruaznao.m3u"
with open(output_file, 'w', encoding='utf-8') as f:
    f.write('\n'.join(m3u_content))

print(f"💾 Salvato in ROOT: {output_file}")
print("✅ Solo italiani, categorizzati perfettamente!")
