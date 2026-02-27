import streamlit as st
import requests
import pandas as pd
import math
import io
from datetime import datetime, timedelta

st.set_page_config(page_title="Tahmin Botu v2.1", page_icon="⚽", layout="wide")

API_KEY = "ce08bcf6a8984a09b6cfdcc541e014a9"
headers = {'X-Auth-Token': API_KEY}

LIGLER = {
    "İngiltere Premier Lig": "PL",
    "İspanya La Liga": "PD",
    "İtalya Serie A": "SA",
    "Almanya Bundesliga": "BL1"
}

@st.cache_data(ttl=3600)
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
            
            # --- YENİ: TARİH VE SAAT FORMATLAMA ---
            ham_tarih = match.get('utcDate', '')
            tarih_str = "Belirsiz"
            if ham_tarih:
                try:
                    # API'den gelen saati anla (Örn: 2024-05-18T14:00:00Z)
                    dt = datetime.strptime(ham_tarih, '%Y-%m-%dT%H:%M:%SZ')
                    # Türkiye saatine göre ayarla (UTC + 3)
                    dt += timedelta(hours=3)
                    # Gözümüze hoş görünecek şekilde formatla
                    tarih_str = dt.strftime('%d.%m.%Y %H:%M')
                except:
                    tarih_str = ham_tarih[:10] # Bir hata olursa sadece tarihi al
            
            if durum == 'FINISHED':
                bitmis.append({
                    'Hafta': hafta,
                    'Tarih': tarih_str,
                    'Ev Sahibi': ev_takimi,
                    'Deplasman': dep_takimi,
                    'Ev Gol': match['score']['fullTime']['home'],
                    'Dep Gol': match['score']['fullTime']['away']
                })
            elif durum in ['SCHEDULED', 'TIMED']: 
                gelecek.append({
                    'Hafta': hafta,
                    'Tarih': tarih_str,
                    'Ev Sahibi': ev_takimi,
                    'Deplasman': dep_takimi
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

st.title("🤖 Yapay Zeka Tahmin Botu v2.1")

secilen_lig_adi = st.sidebar.selectbox("Lig Seçin:", list(LIGLER.keys()))
lig_kodu = LIGLER[secilen_lig_adi]

tab1, tab2 = st.tabs(["📅 Gelecek Fikstür Tahminleri", "✅ Geçmiş Modeli Test Et"])

with tab1:
    if st.button("Gelecek Maçları Analiz Et"):
        with st.spinner('Analiz ediliyor...'):
            mac_tablosu, gelecek_fikstur = verileri_cek(lig_kodu)
            
            if mac_tablosu is not None and not gelecek_fikstur.empty:
                ev_guc, dep_guc, lig_ev_ort, lig_dep_ort = gucleri_hesapla(mac_tablosu)
                
                tahminler = []
                for index, mac in gelecek_fikstur.iterrows():
                    ev = mac['Ev Sahibi']
                    dep = mac['Deplasman']
                    hafta = mac['Hafta']
                    tarih = mac['Tarih'] # Tarihi alıyoruz
                    try:
                        alt_y, ust_y = tahmin_olasiliklarini_al(ev, dep, ev_guc, dep_guc, lig_ev_ort, lig_dep_ort)
                        durum = "ÜST" if ust_y > alt_y else "ALT"
                        yuzde = max(alt_y, ust_y)
                        tahminler.append({
                            "Hafta": hafta,
                            "Tarih ve Saat": tarih, # Tabloya ekliyoruz
                            "Ev Sahibi": ev,
                            "Deplasman": dep,
                            "Tahmin": durum,
                            "İhtimal (%)": round(yuzde, 2)
                        })
                    except KeyError:
                        pass
                
                st.session_state['gelecek_df'] = pd.DataFrame(tahminler)
                st.success("Gelecek maçlar analiz edildi!")
            else:
                st.error("Veri bulunamadı veya henüz oynanacak maç yok.")

    if 'gelecek_df' in st.session_state:
        df = st.session_state['gelecek_df']
        
        mevcut_haftalar = sorted(df['Hafta'].unique())
        secilen_hafta = st.selectbox("Görüntülemek İstediğiniz Haftayı Seçin:", ["Tüm Haftalar"] + list(mevcut_haftalar))
        
        if secilen_hafta != "Tüm Haftalar":
            df_goster = df[df['Hafta'] == secilen_hafta]
        else:
            df_goster = df
            
        st.dataframe(df_goster, use_container_width=True)

with tab2:
    st.markdown("### Modelimizin Geçmiş Başarısı Ne Durumda?")
    st.info("Bu özellik, sistemin bitmiş maçları sanki skorunu bilmiyormuş gibi tahmin etmesini ve gerçek sonuçla kıyaslamasını sağlar.")
    
    if st.button("Son 20 Maçı Test Et"):
        with st.spinner('Geçmiş maçlar test ediliyor...'):
            mac_tablosu, _ = verileri_cek(lig_kodu)
            if mac_tablosu is not None:
                ev_guc, dep_guc, lig_ev_ort, lig_dep_ort = gucleri_hesapla(mac_tablosu)
                
                son_maclar = mac_tablosu.tail(20)
                
                test_sonuclari = []
                dogru_tahmin = 0
                
                for index, mac in son_maclar.iterrows():
                    ev = mac['Ev Sahibi']
                    dep = mac['Deplasman']
                    tarih = mac['Tarih']
                    gercek_toplam = mac['Ev Gol'] + mac['Dep Gol']
                    gercek_durum = "ÜST" if gercek_toplam > 2.5 else "ALT"
                    
                    try:
                        alt_y, ust_y = tahmin_olasiliklarini_al(ev, dep, ev_guc, dep_guc, lig_ev_ort, lig_dep_ort)
                        bot_tahmin = "ÜST" if ust_y > alt_y else "ALT"
                        
                        basarili_mi = "✅" if bot_tahmin == gercek_durum else "❌"
                        if bot_tahmin == gercek_durum:
                            dogru_tahmin += 1
                            
                        test_sonuclari.append({
                            "Tarih": tarih,
                            "Maç": f"{ev} - {dep}",
                            "Gerçek Skor": f"{mac['Ev Gol']} - {mac['Dep Gol']}",
                            "Gerçek Durum": gercek_durum,
                            "Botun Tahmini": bot_tahmin,
                            "Sonuç": basarili_mi
                        })
                    except KeyError:
                        pass
                
                test_df = pd.DataFrame(test_sonuclari)
                st.dataframe(test_df, use_container_width=True)
                st.metric(label="Botun Başarı Oranı (Son 20 Maç)", value=f"% {(dogru_tahmin/20)*100:.1f}")