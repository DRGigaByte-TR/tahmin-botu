import streamlit as st
import requests
import pandas as pd
import math
import sqlite3
from datetime import datetime, timedelta

st.set_page_config(page_title="Tahmin Botu v10.0", page_icon="🏆", layout="wide")

API_KEY = "ce08bcf6a8984a09b6cfdcc541e014a9"
headers = {'X-Auth-Token': API_KEY}

LIGLER = {
    "İngiltere Premier Lig": "PL",
    "İspanya La Liga": "PD",
    "İtalya Serie A": "SA",
    "Almanya Bundesliga": "BL1",
    "Fransa Ligue 1": "FL1",
    "Hollanda Eredivisie": "DED",
    "Portekiz Primeira Liga": "PPL"
}

# --- YENİ VERİ TABANI (Logolar eklendi) ---
def init_db():
    conn = sqlite3.connect('kuponlar.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS kupon_v3 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tarih TEXT,
                    ev_logo TEXT,
                    ev_sahibi TEXT,
                    dep_logo TEXT,
                    deplasman TEXT,
                    tahmin TEXT,
                    oran REAL,
                    formul_skoru REAL,
                    skor TEXT DEFAULT '-',
                    durum TEXT DEFAULT '⏳ Bekliyor',
                    kaynak TEXT DEFAULT 'Manuel'
                )''')
    conn.commit()
    conn.close()

init_db()

def kuponu_kaydet(df, kaynak="Manuel"):
    conn = sqlite3.connect('kuponlar.db')
    for index, row in df.iterrows():
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM kupon_v3 WHERE ev_sahibi=? AND deplasman=? AND kaynak=?", (row['Ev Sahibi'], row['Deplasman'], kaynak))
        if cursor.fetchone() is None:
            conn.execute("INSERT INTO kupon_v3 (tarih, ev_logo, ev_sahibi, dep_logo, deplasman, tahmin, oran, formul_skoru, kaynak) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (row['Tarih'], row.get('Ev Logo', ''), row['Ev Sahibi'], row.get('Dep Logo', ''), row['Deplasman'], row['Tahmin'], row['Botun Adil Oranı'], row['Özel Formül Skoru'], kaynak))
    conn.commit()
    conn.close()

def kayitli_kuponlari_getir():
    conn = sqlite3.connect('kuponlar.db')
    df = pd.read_sql_query("SELECT id, tarih, ev_logo, ev_sahibi, dep_logo, deplasman, tahmin, oran, formul_skoru, skor, durum, kaynak FROM kupon_v3 ORDER BY id DESC", conn)
    conn.close()
    return df

def kuponu_temizle():
    conn = sqlite3.connect('kuponlar.db')
    conn.execute("DELETE FROM kupon_v3")
    conn.commit()
    conn.close()

def skorlari_guncelle():
    conn = sqlite3.connect('kuponlar.db')
    c = conn.cursor()
    c.execute("SELECT id, ev_sahibi, deplasman, tahmin FROM kupon_v3 WHERE durum LIKE '%Bekliyor%'")
    bekleyenler = c.fetchall()
    
    if not bekleyenler:
        conn.close()
        return 0, False

    guncellenen_sayi = 0
    limit_hatasi = False
    tum_bitmis = []
    tum_gelecek = []
    
    for lig_isim, lig_kod in LIGLER.items():
        b_df, g_df = verileri_cek(lig_kod)
        if b_df is None and g_df is None:
            limit_hatasi = True
            break
            
        if b_df is not None and not b_df.empty: tum_bitmis.append(b_df)
        if g_df is not None and not g_df.empty: tum_gelecek.append(g_df)
        
    df_b = pd.concat(tum_bitmis, ignore_index=True) if tum_bitmis else pd.DataFrame()
    df_g = pd.concat(tum_gelecek, ignore_index=True) if tum_gelecek else pd.DataFrame()

    for row in bekleyenler:
        m_id, ev, dep, tahmin = row
        try:
            if not df_b.empty:
                b_match = df_b[(df_b['Ev Sahibi'] == ev) & (df_b['Deplasman'] == dep)]
                if not b_match.empty:
                    b_match = b_match.iloc[0]
                    ev_g = int(float(b_match['Ev Gol']))
                    dep_g = int(float(b_match['Dep Gol']))
                    skor_str = f"{ev_g} - {dep_g}"
                    gercek_durum = "ÜST" if (ev_g + dep_g) > 2.5 else "ALT"
                    sonuc = "✅ Kazandı" if tahmin == gercek_durum else "❌ Kaybetti"
                    c.execute("UPDATE kupon_v3 SET skor=?, durum=? WHERE id=?", (skor_str, sonuc, m_id))
                    guncellenen_sayi += 1
                    continue
                    
            if not df_g.empty:
                g_match = df_g[(df_g['Ev Sahibi'] == ev) & (df_g['Deplasman'] == dep)]
                if not g_match.empty:
                    g_match = g_match.iloc[0]
                    skor_str = str(g_match.get('Güncel Skor', '-'))
                    durum_api = str(g_match.get('Durum', ''))
                    if durum_api in ['IN_PLAY', 'PAUSED'] and skor_str != '-':
                        c.execute("UPDATE kupon_v3 SET skor=? WHERE id=?", (skor_str, m_id))
                        guncellenen_sayi += 1
        except Exception as e:
            continue

    conn.commit()
    conn.close()
    return guncellenen_sayi, limit_hatasi

@st.cache_data(ttl=60)
def verileri_cek(lig_kodu):
    url = f'http://api.football-data.org/v4/competitions/{lig_kodu}/matches'
    response = requests.get(url, headers=headers)
    
    if response.status_code == 429: 
        return None, None
        
    if response.status_code == 200:
        matches = response.json().get('matches', [])
        bitmis = []
        gelecek = []
        simdi = datetime.now()
        
        for match in matches:
            durum = match['status']
            hafta = match.get('matchday', 0)
            
            # LOGOLARI ÇEKİYORUZ!
            ev_takimi = match['homeTeam']['name']
            ev_logo = match['homeTeam'].get('crest', '') 
            dep_takimi = match['awayTeam']['name']
            dep_logo = match['awayTeam'].get('crest', '')
            
            score_data = match.get('score', {})
            full_time = score_data.get('fullTime') or {}
            ev_gol = full_time.get('home')
            dep_gol = full_time.get('away')
            
            ham_tarih = match.get('utcDate', '')
            dt = None
            if ham_tarih:
                try:
                    dt = datetime.strptime(ham_tarih, '%Y-%m-%dT%H:%M:%SZ')
                    dt += timedelta(hours=3)
                    tarih_str = dt.strftime('%d.%m.%Y %H:%M')
                except:
                    tarih_str = ham_tarih[:10]
            
            if durum != 'FINISHED' and dt is not None:
                if dt < (simdi - timedelta(days=2)):
                    continue 
            
            if durum == 'FINISHED':
                if ev_gol is not None and dep_gol is not None:
                    bitmis.append({'Hafta': hafta, 'Tarih': tarih_str, 'Ev Logo': ev_logo, 'Ev Sahibi': ev_takimi, 'Dep Logo': dep_logo, 'Deplasman': dep_takimi, 'Ev Gol': ev_gol, 'Dep Gol': dep_gol})
            elif durum in ['SCHEDULED', 'TIMED', 'IN_PLAY', 'PAUSED']:
                guncel_skor = f"{int(ev_gol)} - {int(dep_gol)}" if (ev_gol is not None and dep_gol is not None) else "-"
                gelecek.append({'Hafta': hafta, 'Tarih': tarih_str, 'Ev Logo': ev_logo, 'Ev Sahibi': ev_takimi, 'Dep Logo': dep_logo, 'Deplasman': dep_takimi, 'Durum': durum, 'Güncel Skor': guncel_skor})
                
        return pd.DataFrame(bitmis), pd.DataFrame(gelecek)
    return None, None

def gucleri_hesapla(df):
    lig_ev_ort = df['Ev Gol'].mean()
    lig_dep_ort = df['Dep Gol'].mean()
    ev_ist = df.groupby('Ev Sahibi').agg({'Ev Gol': 'mean', 'Dep Gol': 'mean'})
    ev_ist.columns = ['Atilan_Ev', 'Yenilen_Ev']
    ev_ist['Hucum_Gucu_Ev'] = ev_ist['Atilan_Ev'] / lig_ev_ort
    ev_ist['Savunma_Gucu_Ev'] = ev_ist['Yenilen_Ev'] / lig_dep_ort 
    dep_ist = df.groupby('Deplasman').agg({'Dep Gol': 'mean', 'Ev Gol': 'mean'})
    dep_ist.columns = ['Atilan_Dep', 'Yenilen_Dep']
    dep_ist['Hucum_Gucu_Dep'] = dep_ist['Atilan_Dep'] / lig_dep_ort
    dep_ist['Savunma_Gucu_Dep'] = dep_ist['Yenilen_Dep'] / lig_ev_ort
    return ev_ist, dep_ist, lig_ev_ort, lig_dep_ort

def tahmin_olasiliklarini_al(ev_takimi, dep_takimi, ev_guc, dep_guc, lig_ev_ort, lig_dep_ort):
    ev_xg = ev_guc.loc[ev_takimi, 'Hucum_Gucu_Ev'] * dep_guc.loc[dep_takimi, 'Savunma_Gucu_Dep'] * lig_ev_ort
    dep_xg = dep_guc.loc[dep_takimi, 'Hucum_Gucu_Dep'] * ev_guc.loc[ev_takimi, 'Savunma_Gucu_Ev'] * lig_dep_ort
    alt_olasiligi = 0.0
    ust_olasiligi = 0.0
    for ev_gol in range(6):
        for dep_gol in range(6):
            ihtimal = (((ev_xg ** ev_gol) * math.exp(-ev_xg)) / math.factorial(ev_gol)) * \
                      (((dep_xg ** dep_gol) * math.exp(-dep_xg)) / math.factorial(dep_gol))
            if ev_gol + dep_gol <= 2: alt_olasiligi += ihtimal
            else: ust_olasiligi += ihtimal
    return alt_olasiligi * 100, ust_olasiligi * 100

def ozel_formul_hesapla(takim, df_bitmis):
    takim_maclari = df_bitmis[(df_bitmis['Ev Sahibi'] == takim) | (df_bitmis['Deplasman'] == takim)].tail(5)
    atilan_gol_toplami = sum([mac['Ev Gol'] if mac['Ev Sahibi'] == takim else mac['Dep Gol'] for index, mac in takim_maclari.iterrows()])
    return atilan_gol_toplami

# Ortak Sütun Yapılandırması (Logolar İçin)
COLUMN_CONFIG = {
    "Kupona Ekle": st.column_config.CheckboxColumn("Seç"),
    "Ev Logo": st.column_config.ImageColumn("", help="Ev Sahibi Logo"),
    "Dep Logo": st.column_config.ImageColumn("", help="Deplasman Logo"),
    "İhtimal (%)": st.column_config.ProgressColumn("İhtimal (%)", format="%f%%", min_value=0, max_value=100)
}

# --- ARAYÜZ ---
st.title("🏆 Yapay Zeka Tahmin Botu v10.0 (Premium UI)")

st.sidebar.markdown("### ⚙️ Genel Ayarlar")
secilen_lig_adi = st.sidebar.selectbox("Lig Seçin:", list(LIGLER.keys()))
lig_kodu = LIGLER[secilen_lig_adi]

st.sidebar.markdown("---")
st.sidebar.markdown("### 🌟 Özel Formül Ayarları")
min_formul = st.sidebar.number_input("Minimum Eşik (Örn: 1.55)", value=1.60, step=0.05)
max_formul = st.sidebar.number_input("Maksimum Eşik (Örn: 2.25)", value=2.10, step=0.05)

tab1, tab2, tab3, tab4 = st.tabs(["🔍 Fikstür", "🔥 AI Hazır Kuponlar", "📱 Takip (Canlı)", "✅ Test Et"])

with tab1:
    if st.button(f"⚽ {secilen_lig_adi} Maçlarını Analiz Et"):
        with st.spinner('Lig verileri çekiliyor, logolar yükleniyor...'):
            mac_tablosu, gelecek_fikstur = verileri_cek(lig_kodu)
            if mac_tablosu is None and gelecek_fikstur is None:
                st.error("⚠️ API Limitine Takıldık! Arka arkaya çok fazla analiz yaptınız. Lütfen 1 dakika bekleyin.")
            elif mac_tablosu is not None and not gelecek_fikstur.empty:
                ev_guc, dep_guc, lig_ev_ort, lig_dep_ort = gucleri_hesapla(mac_tablosu)
                tahminler = []
                for index, mac in gelecek_fikstur.iterrows():
                    ev, dep, hafta, tarih = mac['Ev Sahibi'], mac['Deplasman'], mac['Hafta'], mac['Tarih']
                    ev_logo, dep_logo = mac['Ev Logo'], mac['Dep Logo']
                    durum_api, skor_api = mac['Durum'], mac['Güncel Skor']
                    try:
                        alt_y, ust_y = tahmin_olasiliklarini_al(ev, dep, ev_guc, dep_guc, lig_ev_ort, lig_dep_ort)
                        durum = "ÜST" if ust_y > alt_y else "ALT"
                        yuzde = max(alt_y, ust_y)
                        adil_oran = round(100 / yuzde, 2)
                        
                        ev_son5 = ozel_formul_hesapla(ev, mac_tablosu)
                        dep_son5 = ozel_formul_hesapla(dep, mac_tablosu)
                        formul_skoru = (ev_son5 + dep_son5) / 10
                        yildiz = "🌟" if min_formul <= formul_skoru <= max_formul else ""
                        
                        gosterilecek_skor = skor_api if durum_api in ['IN_PLAY', 'PAUSED'] else "-"
                        tahminler.append({"Kupona Ekle": False, "Hafta": hafta, "Tarih": tarih, "Ev Logo": ev_logo, "Ev Sahibi": ev, "Dep Logo": dep_logo, "Deplasman": dep, "Tahmin": durum, "Botun Adil Oranı": adil_oran, "Özel Formül Skoru": round(formul_skoru, 2), "Yıldız": yildiz, "Canlı Skor": gosterilecek_skor})
                    except KeyError: pass
                
                st.session_state['gelecek_df'] = pd.DataFrame(tahminler)
                st.success("Analiz ve görsel eşleştirmeler tamamlandı!")
            else: st.warning("Veri bulunamadı veya bu ligde oynanacak maç kalmadı.")

    if 'gelecek_df' in st.session_state:
        df = st.session_state['gelecek_df']
        mevcut_haftalar = sorted(df['Hafta'].unique())
        secilen_hafta = st.selectbox("Haftayı Seçin:", ["Tüm Haftalar"] + list(mevcut_haftalar))
        df_goster = df[df['Hafta'] == secilen_hafta] if secilen_hafta != "Tüm Haftalar" else df
            
        edited_df = st.data_editor(
            df_goster, 
            hide_index=True, 
            column_config=COLUMN_CONFIG, 
            disabled=["Hafta", "Tarih", "Ev Logo", "Ev Sahibi", "Dep Logo", "Deplasman", "Tahmin", "Botun Adil Oranı", "Özel Formül Skoru", "Yıldız", "Canlı Skor"], 
            use_container_width=True
        )
        
        secilen_maclar = edited_df[edited_df["Kupona Ekle"] == True]
        if not secilen_maclar.empty:
            if st.button("💾 Seçili Maçları Takibe Al"):
                kuponu_kaydet(secilen_maclar, kaynak="Manuel")
                st.success("Takip sekmesine kaydedildi!")

with tab2:
    st.markdown("### 🔥 Bugün ve Yarının Fırsatları")
    
    if st.button("🚀 Yakın Zamanlı Kuponları Oluştur"):
        with st.spinner("Avrupa maçları logolarıyla birlikte taranıyor..."):
            havuz = []
            limit_hatasi = False
            simdi = datetime.now()
            max_tarih = simdi + timedelta(days=3)
            
            for l_isim, l_kod in LIGLER.items():
                b_df, g_df = verileri_cek(l_kod)
                if b_df is None and g_df is None:
                    limit_hatasi = True
                    break
                    
                if b_df is not None and g_df is not None and not g_df.empty:
                    ev_guc, dep_guc, l_ev_ort, l_dep_ort = gucleri_hesapla(b_df)
                    for _, mac in g_df.iterrows():
                        ev, dep, tarih_str = mac['Ev Sahibi'], mac['Deplasman'], mac['Tarih']
                        ev_logo, dep_logo = mac['Ev Logo'], mac['Dep Logo']
                        
                        try:
                            mac_tarihi = datetime.strptime(tarih_str, '%d.%m.%Y %H:%M')
                            if not (simdi.date() <= mac_tarihi.date() <= max_tarih.date()): continue
                        except: continue

                        try:
                            alt_y, ust_y = tahmin_olasiliklarini_al(ev, dep, ev_guc, dep_guc, l_ev_ort, l_dep_ort)
                            durum = "ÜST" if ust_y > alt_y else "ALT"
                            yuzde = max(alt_y, ust_y)
                            
                            ev_son5 = ozel_formul_hesapla(ev, b_df)
                            dep_son5 = ozel_formul_hesapla(dep, b_df)
                            formul_skoru = (ev_son5 + dep_son5) / 10
                            
                            havuz.append({
                                "Lig": l_isim, "Tarih": tarih_str, "Ev Logo": ev_logo, "Ev Sahibi": ev, 
                                "Dep Logo": dep_logo, "Deplasman": dep, "Tahmin": durum, "İhtimal (%)": round(yuzde, 2), 
                                "Botun Adil Oranı": round(100/yuzde, 2), "Özel Formül Skoru": round(formul_skoru, 2)
                            })
                        except: pass
            
            if limit_hatasi:
                st.error("⚠️ API Limitine Takıldık! Lütfen 1 dakika bekleyip tekrar tıklayın.")
            elif havuz:
                havuz_df = pd.DataFrame(havuz)
                st.session_state['banko_kupon'] = havuz_df.sort_values(by="İhtimal (%)", ascending=False).head(4)
                f_kupon = havuz_df[(havuz_df["Özel Formül Skoru"] >= min_formul) & (havuz_df["Özel Formül Skoru"] <= max_formul)]
                st.session_state['formul_kupon'] = f_kupon.sort_values(by="İhtimal (%)", ascending=False).head(4)

    if 'banko_kupon' in st.session_state:
        st.markdown("#### 🤖 Yapay Zeka Banko Kupon")
        st.dataframe(st.session_state['banko_kupon'][['Lig', 'Tarih', 'Ev Logo', 'Ev Sahibi', 'Dep Logo', 'Deplasman', 'Tahmin', 'İhtimal (%)', 'Botun Adil Oranı']], hide_index=True, column_config=COLUMN_CONFIG)
        if st.button("💾 AI Banko Kuponunu Takibe Al"):
            kuponu_kaydet(st.session_state['banko_kupon'], kaynak="AI")
            st.success("Eklendi!")

        st.markdown("---")
        st.markdown("#### 🌟 Özel Formül Kuponun")
        if not st.session_state['formul_kupon'].empty:
            st.dataframe(st.session_state['formul_kupon'][['Lig', 'Tarih', 'Ev Logo', 'Ev Sahibi', 'Dep Logo', 'Deplasman', 'Tahmin', 'İhtimal (%)', 'Özel Formül Skoru']], hide_index=True, column_config=COLUMN_CONFIG)
            if st.button("💾 Formül Kuponunu Takibe Al"):
                kuponu_kaydet(st.session_state['formul_kupon'], kaynak="Formul")
                st.success("Eklendi!")

with tab3:
    st.markdown("### 📱 Takip Ettiğim Maçlar (Canlı Kupon)")
    
    col_guncelle, _ = st.columns([1, 2])
    with col_guncelle:
        if st.button("🔄 Skorları ve Sonuçları Güncelle", use_container_width=True):
            with st.spinner("Skorlar güncelleniyor..."):
                verileri_cek.clear()
                g_sayi, limit_var_mi = skorlari_guncelle()
                if limit_var_mi:
                    st.error("⚠️ Limit! 1 dakika bekle.")
                else:
                    st.success(f"Güncelleme Tamamlandı! ({g_sayi} maç yenilendi)")
                
    kayitli_df = kayitli_kuponlari_getir()
    
    if not kayitli_df.empty:
        def tablo_bas(df_alt, baslik):
            if not df_alt.empty:
                st.markdown(baslik)
                gosterim = df_alt[['tarih', 'ev_logo', 'ev_sahibi', 'dep_logo', 'deplasman', 'tahmin', 'oran', 'formul_skoru', 'skor', 'durum']]
                gosterim.columns = ['Tarih', 'Ev Logo', 'Ev Sahibi', 'Dep Logo', 'Deplasman', 'Tahmin', 'Oran/İhtimal', 'Formül Skoru', 'Skor', 'Durum']
                st.dataframe(gosterim, hide_index=True, use_container_width=True, column_config=COLUMN_CONFIG)

        df_manuel = kayitli_df[kayitli_df['kaynak'] == 'Manuel']
        df_ai = kayitli_df[kayitli_df['kaynak'] == 'AI']
        df_formul = kayitli_df[kayitli_df['kaynak'] == 'Formul']

        tablo_bas(df_manuel, "#### 🕵️ Kendi Seçtiğim Maçlar")
        tablo_bas(df_ai, "#### 🤖 Yapay Zeka Banko Kupon")
        tablo_bas(df_formul, "#### 🌟 Özel Formül Kuponu")
        
        st.markdown("<br><br><br>", unsafe_allow_html=True)
        with st.expander("⚠️ Tehlikeli Alan (Tüm Kuponları Sil)"):
            if st.button("🗑️ Hepsini Temizle"):
                kuponu_temizle()
                st.rerun()
    else:
        st.info("Henüz kaydedilmiş bir maçınız bulunmuyor.")

with tab4:
    st.markdown("### ⚖️ Modelleri Test Et (Son 50 Maç)")
    if st.button("Tarihi Testi Başlat"):
        with st.spinner('Taranıyor...'):
            mac_tablosu, _ = verileri_cek(lig_kodu)
            if mac_tablosu is not None:
                ev_guc, dep_guc, lig_ev_ort, lig_dep_ort = gucleri_hesapla(mac_tablosu)
                son_maclar = mac_tablosu.tail(50)
                test_sonuclari = []
                bot_dogru = formul_tet_sayi = formul_dogru = 0
                for index, mac in son_maclar.iterrows():
                    ev, dep, tarih = mac['Ev Sahibi'], mac['Deplasman'], mac['Tarih']
                    ev_logo, dep_logo = mac['Ev Logo'], mac['Dep Logo']
                    gercek_toplam = mac['Ev Gol'] + mac['Dep Gol']
                    gercek_durum = "ÜST" if gercek_toplam > 2.5 else "ALT"
                    try:
                        alt_y, ust_y = tahmin_olasiliklarini_al(ev, dep, ev_guc, dep_guc, lig_ev_ort, lig_dep_ort)
                        bot_tahmin = "ÜST" if ust_y > alt_y else "ALT"
                        bot_basarili_mi = "✅" if bot_tahmin == gercek_durum else "❌"
                        if bot_tahmin == gercek_durum: bot_dogru += 1
                        
                        ev_son5 = ozel_formul_hesapla(ev, mac_tablosu)
                        dep_son5 = ozel_formul_hesapla(dep, mac_tablosu)
                        f_skor = (ev_son5 + dep_son5) / 10
                        f_tahmin = f_sonuc = "-"
                        if min_formul <= f_skor <= max_formul:
                            f_tahmin = "ÜST (🌟)"
                            formul_tet_sayi += 1
                            if gercek_durum == "ÜST":
                                f_sonuc = "✅"
                                formul_dogru += 1
                            else: f_sonuc = "❌"
                                
                        test_sonuclari.append({"Ev Logo": ev_logo, "Ev Sahibi": ev, "Dep Logo": dep_logo, "Deplasman": dep, "Gerçek": gercek_durum, "Bot Tahmin": bot_tahmin, "Bot Sonuç": bot_basarili_mi, "Formül Skoru": round(f_skor, 2), "Formül Sonuç": f_sonuc})
                    except KeyError: pass
                st.dataframe(pd.DataFrame(test_sonuclari), use_container_width=True, column_config=COLUMN_CONFIG)
