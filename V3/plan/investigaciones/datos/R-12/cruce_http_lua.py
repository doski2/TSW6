"""R-12: cruza los volcados HTTP de la M3A con lo que leyó el laboratorio Lua de V2.

Uso (sin juego):
    python -I cruce_http_lua.py <carpeta_volcados_http> <carpeta_export_lab> <carpeta_salida>

Solo lee ficheros; no toca el juego. Escribe en <carpeta_salida>:
- todo.csv: una fila por campo HTTP de CurrentDrivableActor, DriverAid y DriverInput (no va a git).
- freno_v1.csv: solo los campos que responden por HTTP y parecen útiles para frenar (v1).
"""
import csv, json, os, re, sys

http_dir, lab_dir, out_dir = sys.argv[1:4]

def walk(node, acc):
    acc.extend(node.get("endpoints") or [])
    for ch in node.get("children") or []:
        walk(ch, acc)

rows = []
for f in sorted(os.listdir(http_dir)):
    j = json.load(open(os.path.join(http_dir, f), encoding="utf-8"))
    walk(j["tree"], rows)

def http_state(v):
    if v == "INVALID":
        return "invalid"
    if isinstance(v, str) and "SKIPPED" in v:
        return "skipped_unsafe"
    return "ok"

lab = lambda n: json.load(open(os.path.join(lab_dir, n), encoding="utf-8"))
hud = lab("hud_batch.json")["lua"]
da = lab("driver_aid.json")["lua"]
levers = {l["name"]: l for l in lab("controls.json")["lua"]["levers"]}
sim_nodes = {r["node"] for r in lab("formation_http.json")["rows"]}

BRAKE = re.compile(r"brake|pressure|cylinder|reservoir|pipe|MasterController|HUD_Get(Speed|Acceleration|BrakeGauge|TrainBrake|MaxPermitted)"
                   r"|DriverAid|ACSES|ATC_|PTS_|Enum_Brake|Emergency|Deadman|Alerter|Speed", re.I)

def classify(p):
    """Devuelve (grupo, componente, intento_lua)."""
    if p.startswith("DriverAid"):
        field = p.split(".")[-1]
        if "TrackData" in p:
            return "DriverAid", "TrackData", "no (solo HTTP)"
        return "DriverAid", "Data", "sí, leído (campos sueltos de Data)"
    if p.startswith("DriverInput"):
        comp = p.split("/")[1].split(".")[0]
        if comp in levers:
            return "DriverInput", comp, "mismo mando leído en el actor"
        return "DriverInput", comp, "no intentado"
    rest = p[len("CurrentDrivableActor"):].lstrip("/.")
    if rest.startswith("Function.HUD_"):
        fn = rest.split(".")[1]
        return "HUD", fn, "sí, leído" if fn in hud else "no intentado"
    if rest.startswith("Property.Simulation_"):
        return "Ref. a Simulation (propiedad del actor)", "actor", "no intentado"
    if rest.startswith(("Property.", "Function.")):
        return "Actor", "actor", "no intentado"
    comp = rest.split(".")[0]
    if comp.startswith("Simulation/"):
        node = comp.split("/")[1]
        return "Simulation", comp, "sí, falló (nodo sin campos)" if node in sim_nodes else "no intentado"
    if comp in levers:
        return "Mando (VHID)", comp, "componente leído (solo algunas propiedades)"
    if "ACSES_ATC" in comp:
        return "Seguridad ACSES/ATC", comp, "no intentado"
    return "Otros componentes", comp, "no intentado"

HEAD = ["grupo", "componente", "ruta_http", "estado_http", "valor_http", "lua", "freno_v1"]
with open(os.path.join(out_dir, "todo.csv"), "w", newline="", encoding="utf-8") as fa,      open(os.path.join(out_dir, "freno_v1.csv"), "w", newline="", encoding="utf-8") as fb:
    wa, wb = csv.writer(fa), csv.writer(fb)
    wa.writerow(HEAD); wb.writerow(HEAD)
    for e in rows:
        p = e["full_path"]
        if not p.startswith(("CurrentDrivableActor", "DriverAid", "DriverInput")):
            continue
        g, c, lua = classify(p)
        v = e.get("value")
        st = http_state(v)
        brake = bool(BRAKE.search(p))
        row = [g, c, p, st, json.dumps(v, ensure_ascii=False)[:120], lua, "sí" if brake else ""]
        wa.writerow(row)
        # HUD: el crawler HTTP las salta (unsafe) pero Lua sí las lee -> también entran.
        if brake and (st == "ok" or g == "HUD"):
            wb.writerow(row)
