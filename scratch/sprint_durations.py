import pandas as pd

df = pd.read_csv("Panel Title-data-2026-09-30 08_11_24.csv")
df["is_sprint"] = (df["motivo_codigo"] == "SPRINT_SOBREVELOCIDADE")

# Calculate lengths of sprint episodes
blocks = (df["is_sprint"] != df["is_sprint"].shift(1)).cumsum()
sprint_blocks = df[df["is_sprint"]].groupby(blocks).size() * 10 # 10s per point

print("=== DISTRIBUIÇÃO DAS DURAÇÕES DE SPRINT ===")
print("Total de episódios de Sprint:", len(sprint_blocks))
print("Duração Média de cada Sprint:", f"{sprint_blocks.mean():.1f} s ({sprint_blocks.mean()/60:.1f} min)")
print("Duração Mediana:", f"{sprint_blocks.median():.1f} s")
print("Duração Mínima:", f"{sprint_blocks.min():.1f} s")
print("Duração Máxima:", f"{sprint_blocks.max():.1f} s ({sprint_blocks.max()/60:.1f} min)")
print("\nEpisódios curtos (< 30s):", (sprint_blocks < 30).sum())
print("Episódios médios (30s a 2min):", ((sprint_blocks >= 30) & (sprint_blocks <= 120)).sum())
print("Episódios longos (> 2min):", (sprint_blocks > 120).sum())
