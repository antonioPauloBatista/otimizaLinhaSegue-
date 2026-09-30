import pandas as pd

df = pd.read_csv("Panel Title-data-2026-09-30 08_11_24.csv")
df_old = pd.read_csv("Panel Title-data-2026-09-29 08_44_34.csv")

print("=== BUFFERS & VELOCIDADES MÉDIAS ===")
for name, d in [("28-29/09 (Anterior)", df_old), ("29-30/09 (Atual)", df)]:
    print(f"\n--- {name} ---")
    for b in ["b1_pct", "b2_pct", "b3_pct", "b4_pct"]:
        if b in d.columns:
            print(f"  {b}: mean={d[b].mean():.1f}%, std={d[b].std():.1f}%, min={d[b].min():.1f}%, max={d[b].max():.1f}%")
    for v in ["v_in_cph", "v_atual_cph", "v_out_cph", "v_setpoint_cph"]:
        if v in d.columns:
            print(f"  {v}: mean={d[v].mean():.1f} CPH")

