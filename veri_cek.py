import streamlit as st
import requests
import pandas as pd
import math
import sqlite3
from datetime import datetime, timedelta

st.set_page_config(page_title="Tahmin Botu v4.0 App", page_icon="📱", layout="wide")

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

# --- VERİ TABANI (SQLITE) KURULUMU ---
def init_db():
    conn = sqlite3.connect('kuponlar.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS kupon (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tarih TEXT,
                    ev_sahibi TEXT,
                    deplasman TEXT,
                    tahmin TEXT,
                    oran REAL,
                    formul_skoru REAL,
                    skor TEXT DEFAULT '-',
                    durum TEXT DEFAULT 'Bekliyor'
                )''')
    conn.commit()
    conn.close()

init_db()

def kuponu_kaydet(df):
    conn = sqlite3.connect('kuponlar.db')
    for index, row in df.iterrows():
        # Aynı maçı iki kere kaydetmemek için kontrol edelim
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM kupon WHERE ev_sahibi=? AND deplasman=?", (row['Ev Sahibi'], row['Deplasman']))
        if cursor.fetchone() is None:
            conn.execute("INSERT INTO kupon (tarih, ev_sahibi, deplasman, tahmin, oran, formul_skoru) VALUES (?, ?, ?, ?, ?, ?)",
                         (row['Tarih'], row['Ev Sahibi'], row['Deplasman'], row['Tahmin'], row['Botun Adil Oranı'], row['Özel Formül Skoru']))
    conn.commit()
    conn.close()

def kayitli_kuponlari_getir():
    conn = sqlite3.connect('kuponlar.db')
    df = pd.read_sql_query("SELECT id, tarih, ev_sahibi, deplasman, tahmin, oran, formul_skoru, skor, durum FROM kupon ORDER BY id DESC", conn)
    conn.close()
    return df

def kuponu_temizle():
    conn = sqlite3.connect('kuponlar.db')
    conn.execute("DELETE FROM kupon")
    conn.commit()
    conn.close()

# --- ARKA PLAN FONKSİYONLARI ---
@st.cache_data(ttl=60) # Veriyi 1 dakika tutar (Canlı skor için süreyi kısalttık)
def verileri_cek(lig_kodu):
    url = f'http://api.football-data.org/v4/competitions/{lig_kodu}/matches'
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        matches = response.json().get('matches', [])
        bitmis = []
        gelecek = []
        for match in matches:
            durum = match['status']
            hafta = match.get('matchday', 0)
            ev_takimi = match['homeTeam']['name']
            dep_takimi = match['awayTeam']['name']
            
            # Canlı veya Bitmiş Skor Bilgisi
            ev_gol = match['score']['fullTime']['home']
            dep_gol = match['score']['fullTime']['away']
            guncel_skor = f"{ev_gol} - {dep_gol}" if ev_gol is not None else "-"
            
            ham_tarih = match.get('utcDate', '')
            tarih_str = "Belirsiz"
            if ham_tarih:
                try:
                    dt = datetime.strptime(ham_tarih, '%Y-%m-%dT%H:%M:%SZ')
                    dt += timedelta(hours=3)
                    tarih_str = dt.strftime('%d.%m.%Y %H:%M')
                except:
                    tarih_str = ham_tarih[:10]
            
            if durum == 'FINISHED':
                bitmis.append({
                    'Hafta': hafta,
                    'Tarih': tarih_str,
                    'Ev Sahibi': ev_takimi,
                    'Deplasman': dep_takimi,
                    'Ev Gol': ev_gol,
                    'Dep Gol': dep_gol
                })
            elif durum in ['SCHEDULED', 'TIMED', 'IN_PLAY', 'PAUSED']: 
                gelecek.append({
                    'Hafta': hafta,
                    'Tarih': tarih_str,
                    'Ev Sahibi': ev_takimi,
                    'Deplasman': dep_takimi,
                    'Durum': durum,
                    'Güncel Skor': guncel_skor
                })
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
            if ev_gol + dep_gol <= 2:
                alt_olasiligi += ihtimal
            else:
                ust_olasiligi += ihtimal
    return alt_olasiligi * 100, ust_olasiligi * 100

def ozel_formul_hesapla(takim, df_bitmis):
    takim_maclari = df_bitmis[(df_bitmis['Ev Sahibi'] == takim) | (df_bitmis['Deplasman'] == takim)].tail(5)
    atilan_gol_toplami = sum([mac['Ev Gol'] if mac['Ev Sahibi'] == takim else mac['Dep Gol'] for index, mac in takim_maclari.iterrows()])
    return atilan_gol_toplami

# --- ARAYÜZ ---
st.title("🤖 Yapay Zeka Tahmin Botu v4.0")

secilen_lig_adi = st.sidebar.selectbox("Lig Seçin:", list(LIGLER.keys()))
lig_kodu = LIGLER[secilen_lig_adi]

# Yeni sekmelerimiz
tab1, tab2, tab3 = st.tabs(["🔍 Fikstür Analizi", "📱 Kayıtlı Kuponlarım (Takip)", "✅ Geçmiş Modeli Test Et"])

with tab1:
    if st.button(f"{secilen_lig_adi} Maçlarını Analiz Et"):
        with st.spinner('Analiz ediliyor...'):
            mac_tablosu, gelecek_fikstur = verileri_cek(lig_kodu)
            
            if mac_tablosu is not None and not gelecek_fikstur.empty:
                ev_guc, dep_guc, lig_ev_ort, lig_dep_ort = gucleri_hesapla(mac_tablosu)
                
                tahminler = []
                for index, mac in gelecek_fikstur.iterrows():
                    ev, dep, hafta, tarih = mac['Ev Sahibi'], mac['Deplasman'], mac['Hafta'], mac['Tarih']
                    durum_api, skor_api = mac['Durum'], mac['Güncel Skor']
                    try:
                        alt_y, ust_y = tahmin_olasiliklarini_al(ev, dep, ev_guc, dep_guc, lig_ev_ort, lig_dep_ort)
                        durum = "ÜST" if ust_y > alt_y else "ALT"
                        yuzde = max(alt_y, ust_y)
                        adil_oran = round(100 / yuzde, 2)
                        
                        ev_son5 = ozel_formul_hesapla(ev, mac_tablosu)
                        dep_son5 = ozel_formul_hesapla(dep, mac_tablosu)
                        formul_skoru = (ev_son5 + dep_son5) / 10
                        yildiz = "🌟" if 1.60 <= formul_skoru <= 2.10 else ""
                        
                        # Eğer maç oynanıyorsa skor sütununda göstersin
                        gosterilecek_skor = skor_api if durum_api in ['IN_PLAY', 'PAUSED', 'FINISHED'] else "-"
                        
                        tahminler.append({
                            "Kupona Ekle": False,
                            "Hafta": hafta,
                            "Tarih": tarih,
                            "Ev Sahibi": ev,
                            "Deplasman": dep,
                            "Tahmin": durum,
                            "Botun Adil Oranı": adil_oran,
                            "Özel Formül Skoru": round(formul_skoru, 2),
                            "Yıldız": yildiz,
                            "Canlı Skor": gosterilecek_skor
                        })
                    except KeyError:
                        pass
                
                st.session_state['gelecek_df'] = pd.DataFrame(tahminler)
                st.success("Tüm analizler tamamlandı!")
            else:
                st.error("Veri bulunamadı.")

    if 'gelecek_df' in st.session_state:
        df = st.session_state['gelecek_df']
        mevcut_haftalar = sorted(df['Hafta'].unique())
        secilen_hafta = st.selectbox("Görüntülemek İstediğiniz Haftayı Seçin:", ["Tüm Haftalar"] + list(mevcut_haftalar))
        
        if secilen_hafta != "Tüm Haftalar":
            df_goster = df[df['Hafta'] == secilen_hafta]
        else:
            df_goster = df
            
        edited_df = st.data_editor(
            df_goster,
            hide_index=True,
            column_config={"Kupona Ekle": st.column_config.CheckboxColumn("Seç")},
            disabled=["Hafta", "Tarih", "Ev Sahibi", "Deplasman", "Tahmin", "Botun Adil Oranı", "Özel Formül Skoru", "Yıldız", "Canlı Skor"],
            use_container_width=True
        )
        
        secilen_maclar = edited_df[edited_df["Kupona Ekle"] == True]
        if not secilen_maclar.empty:
            if st.button("💾 Seçili Maçları Uygulamaya Kaydet"):
                kuponu_kaydet(secilen_maclar)
                st.success("Kupon başarıyla 'Kayıtlı Kuponlarım' sekmesine kaydedildi!")

with tab2:
    st.markdown("### 📱 Takip Ettiğim Maçlar")
    st.info("Bu ekranda kaydettiğin maçları görebilirsin. Canlı skorlar uygulamada analiz butonuna her bastığında güncellenir.")
    
    kayitli_df = kayitli_kuponlari_getir()
    
    if not kayitli_df.empty:
        # Sadece göze hoş görünen kısımları ekrana basalım
        gosterim_df = kayitli_df[['tarih', 'ev_sahibi', 'deplasman', 'tahmin', 'oran', 'formul_skoru', 'skor']]
        gosterim_df.columns = ['Tarih', 'Ev Sahibi', 'Deplasman', 'Senin Tahminin', 'Oran', 'Senin Formülün', 'Skor Durumu']
        
        st.dataframe(gosterim_df, hide_index=True, use_container_width=True)
        
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("🗑️ Kuponu Temizle"):
                kuponu_temizle()
                st.rerun()
    else:
        st.warning("Henüz kaydedilmiş bir maçınız bulunmuyor. Fikstürden maç seçip kaydedebilirsiniz.")

with tab3:
    st.markdown("### Modelimizin Geçmiş Başarısı Ne Durumda?")
    if st.button("Son 20 Maçı Test Et"):
        with st.spinner('Test ediliyor...'):
            mac_tablosu, _ = verileri_cek(lig_kodu)
            if mac_tablosu is not None:
                ev_guc, dep_guc, lig_ev_ort, lig_dep_ort = gucleri_hesapla(mac_tablosu)
                son_maclar = mac_tablosu.tail(20)
                test_sonuclari = []
                dogru = 0
                for index, mac in son_maclar.iterrows():
                    ev, dep, tarih = mac['Ev Sahibi'], mac['Deplasman'], mac['Tarih']
                    gercek_toplam = mac['Ev Gol'] + mac['Dep Gol']
                    gercek_durum = "ÜST" if gercek_toplam > 2.5 else "ALT"
                    try:
                        alt_y, ust_y = tahmin_olasiliklarini_al(ev, dep, ev_guc, dep_guc, lig_ev_ort, lig_dep_ort)
                        bot_tahmin = "ÜST" if ust_y > alt_y else "ALT"
                        basarili_mi = "✅" if bot_tahmin == gercek_durum else "❌"
                        if bot_tahmin == gercek_durum: dogru += 1
                        test_sonuclari.append({"Maç": f"{ev} - {dep}", "Gerçek": gercek_durum, "Bot": bot_tahmin, "Sonuç": basarili_mi})
                    except KeyError: pass
                st.dataframe(pd.DataFrame(test_sonuclari), use_container_width=True)
                st.metric("Başarı Oranı", f"% {(dogru/len(test_sonuclari))*100:.1f}")
