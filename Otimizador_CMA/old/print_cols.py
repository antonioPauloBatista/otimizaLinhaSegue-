import requests
import json
from controlador_velocidade_cma_es_live import obter_dados_tempo_real, obter_ds_uid, carregar_configuracao

session = requests.Session()
ds_uid = obter_ds_uid(session)
config = carregar_configuracao()
df = obter_dados_tempo_real(session, config, ds_uid)
if df is not None:
    print(list(df.columns))
else:
    print("DF is None")
