"""Robô do Alerta que Instrui (roda no GitHub Actions a cada ~10 minutos).

Lê duas fontes oficiais e salva o resultado em JSON para o app:
  - alertas.json      -> alertas da Defesa Civil em vigor (feed IDAP/CAP do Ministério da Integração)
  - alagamentos.json  -> pontos de alagamento ativos agora na cidade de SP (CGE, Prefeitura de SP)
Só usa a biblioteca padrão do Python. Se uma fonte falhar, grava fonte_ok=false e o app volta ao modo normal.
"""
import json, re, sys, os, hashlib, html
import urllib.request
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
import xml.etree.ElementTree as ET

OUT = sys.argv[1] if len(sys.argv) > 1 else "."
os.makedirs(OUT, exist_ok=True)
AGORA = datetime.now(timezone.utc)
UA = {"User-Agent": "Mozilla/5.0 (AlertaQueInstrui; projeto escolar; +https://github.com)"}
IDAP = "https://idapfile.mdr.gov.br/idap/api/rss/cap"
CGE = "https://www.cgesp.org/v3/alagamentos.jsp"


def baixar(url, timeout=40):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")


def local(tag):
    return tag.rsplit("}", 1)[-1].lower()


def filhos(el, nome):
    return [c for c in el.iter() if local(c.tag) == nome]


def texto(el, nome):
    for c in el.iter():
        if local(c.tag) == nome and (c.text or "").strip():
            return c.text.strip()
    return ""


def data_iso(s):
    try:
        d = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def ler_cap(alert):
    infos = filhos(alert, "info") or [alert]
    info = next((i for i in infos if texto(i, "language").lower().startswith("pt")), infos[0])
    areas = [texto(a, "areadesc") for a in filhos(info, "area")] or [texto(info, "areadesc")]
    poligonos = []
    for pg in filhos(info, "polygon"):
        pts = []
        for par in (pg.text or "").split():
            try:
                la, lo = par.split(",")[:2]; pts.append([round(float(la), 3), round(float(lo), 3)])
            except Exception:
                pass
        if len(pts) >= 3:
            poligonos.append(pts[::max(1, len(pts) // 400)])
    expira = texto(info, "expires")
    return {
        "id": texto(alert, "identifier") or hashlib.sha1(ET.tostring(alert)).hexdigest()[:16],
        "enviado": texto(alert, "sent"),
        "expira": expira,
        "evento": texto(info, "event"),
        "gravidade": texto(info, "severity"),
        "titulo": texto(info, "headline"),
        "descricao": texto(info, "description"),
        "instrucao": texto(info, "instruction"),
        "area": "; ".join(a for a in areas if a)[:600],
        "poligonos": poligonos[:20],
    }


def alertas():
    bruto = baixar(IDAP)
    raiz = ET.fromstring(bruto.encode("utf-8"))
    achados = [ler_cap(a) for a in filhos(raiz, "alert")]
    if not achados:  # o feed só lista links: abre cada alerta CAP
        itens = filhos(raiz, "item") or filhos(raiz, "entry")
        for it in itens[:60]:
            link = texto(it, "link") or texto(it, "guid")
            for l in filhos(it, "link"):
                link = l.get("href") or link
            titulo, desc = texto(it, "title"), texto(it, "description") or texto(it, "summary")
            cap = None
            if link and link.startswith("http"):
                try:
                    r2 = ET.fromstring(baixar(link, 25).encode("utf-8"))
                    caps = filhos(r2, "alert") or ([r2] if local(r2.tag) == "alert" else [])
                    cap = ler_cap(caps[0]) if caps else None
                except Exception:
                    cap = None
            if not cap:
                cap = {"id": hashlib.sha1((link + titulo).encode()).hexdigest()[:16], "enviado": texto(it, "pubdate"), "expira": "",
                       "evento": "", "gravidade": "", "titulo": titulo, "descricao": html.unescape(re.sub("<[^>]+>", " ", desc)).strip(),
                       "instrucao": "", "area": titulo}
            achados.append(cap)
    sp = []
    for a in achados:
        if a["area"]:
            if not re.search(r"/\s*SP\b", a["area"], re.I):
                continue
        elif not re.search(r"S[ãa]o Paulo(?! de Oliven)|\bSP\b", a["titulo"] + " " + a["descricao"], re.I):
            continue
        exp = data_iso(a["expira"]) if a["expira"] else None
        if exp and exp < AGORA:
            continue
        sp.append(a)
    return {"total_no_feed": len(achados), "alertas": sp[:30]}, bruto[:3000]


class Texto(HTMLParser):
    def __init__(self):
        super().__init__(); self.partes = []; self.pular = 0
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"): self.pular += 1
        if tag in ("br", "li", "p", "div", "tr", "h1", "h2", "h3", "h4", "td"): self.partes.append("\n")
    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.pular: self.pular -= 1
    def handle_data(self, d):
        if not self.pular: self.partes.append(d)


RUA = re.compile(r"^(Av\.?|Avenida|R\.|Rua|Viaduto|T[úu]nel|Ponte|P[çc]a\.?|Pra[çc]a|Marginal|Estr\.?|Estrada|Al\.?|Alameda|Largo|Complexo|Pass(agem)?\.?|Vd\.?|Tv\.?|Travessa)(?![A-Za-zÀ-ú])", re.I)


def alagamentos():
    bruto = baixar(CGE)
    p = Texto(); p.feed(bruto)
    linhas = [re.sub(r"\s+", " ", l).strip() for l in "".join(p.partes).split("\n")]
    linhas = [l for l in linhas if l]
    junto = "\n".join(linhas)
    tr = re.findall(r"Transit[áa]veis\s*=\s*(\d+)", junto, re.I)
    it = re.findall(r"Intransit[áa]veis\s*=\s*(\d+)", junto, re.I)
    if not tr and not it:
        raise ValueError("não achei os contadores de alagamento na página")
    ativos = {"transitaveis": int(tr[0]) if tr else 0, "intransitaveis": int(it[0]) if it else 0}
    # lista de pontos (melhor esforço): endereços que aparecem antes do bloco "Inativos"
    corte = next((i for i, l in enumerate(linhas) if re.match(r"^Inativos", l, re.I)), len(linhas))
    pontos = []
    for i, l in enumerate(linhas[:corte]):
        if RUA.match(l) and len(l) < 140:
            det = " ".join(x for x in linhas[i + 1:i + 3] if re.search(r"Sentido|Refer|De \d|\d{2}:\d{2}", x))[:120]
            pontos.append({"local": l, "detalhe": det})
    return {"ativos": ativos, "pontos": pontos[:50] if sum(ativos.values()) else []}, junto[:3000]


def salvar(nome, fonte, fn):
    dados = {"atualizado": AGORA.isoformat(timespec="seconds"), "fonte": fonte, "fonte_ok": False, "erro": None}
    amostra = ""
    try:
        res, amostra = fn()
        dados.update(res); dados["fonte_ok"] = True
    except Exception as e:
        dados["erro"] = f"{type(e).__name__}: {e}"[:300]
    with open(os.path.join(OUT, nome), "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT, nome.replace(".json", "-amostra.txt")), "w", encoding="utf-8") as f:
        f.write(amostra or "")
    print(nome, "ok" if dados["fonte_ok"] else "FALHOU", dados.get("erro") or "")


salvar("alertas.json", "Defesa Civil (IDAP, Ministério da Integração)", alertas)


# ---------- Avisos no celular pelo OneSignal (só roda se as chaves estiverem nos "Secrets" do GitHub) ----------
def slug(n):
    import unicodedata
    n = unicodedata.normalize("NFD", n).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]+", "-", n).strip("-")


# pontos da capital (centro e as quatro zonas) para saber se o desenho do alerta pega a cidade de SP
CAPITAL = [(-23.55, -46.633), (-23.47, -46.63), (-23.68, -46.70), (-23.54, -46.47), (-23.57, -46.73), (-23.80, -46.70)]


def dentro(lat, lng, pts):
    d = False
    j = len(pts) - 1
    for i in range(len(pts)):
        yi, xi = pts[i]; yj, xj = pts[j]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
            d = not d
        j = i
    return d


def alvo_do_alerta(a, cidades):
    polys = a.get("poligonos") or []
    if polys:
        alvo = [slug(c[0]) for c in cidades if any(dentro(c[1], c[2], p) for p in polys)]
        if any(dentro(la, lo, p) for la, lo in CAPITAL for p in polys):
            alvo.append("sao-paulo")
        return alvo
    txt = re.sub(r"estado de S[ãa]o Paulo", " ", a.get("titulo", "") + " " + a.get("descricao", ""), flags=re.I)
    alvo = [slug(c[0]) for c in cidades if re.search(r"\b" + re.escape(c[0]) + r"\b", txt, re.I)]
    if re.search(r"S[ãa]o Paulo|capital paulista|Grande SP", txt, re.I):
        alvo.append("sao-paulo")
    return alvo


def enviar_avisos():
    app_id, chave = os.environ.get("ONESIGNAL_APP_ID", "").strip(), os.environ.get("ONESIGNAL_API_KEY", "").strip()
    antes_p = os.path.join(OUT, "enviados_antes.json")
    try:
        enviados = json.load(open(antes_p, encoding="utf-8"))
    except Exception:
        enviados = []
    try:
        dados = json.load(open(os.path.join(OUT, "alertas.json"), encoding="utf-8"))
    except Exception:
        dados = {}
    if not (app_id and chave and dados.get("fonte_ok")):
        json.dump(enviados[-300:], open(os.path.join(OUT, "enviados.json"), "w"), ensure_ascii=False)
        print("avisos: sem chaves do OneSignal ou sem dados; nada enviado")
        return
    try:
        cidades = json.load(open("cidades-sp.json", encoding="utf-8"))
    except Exception:
        cidades = []
    site = os.environ.get("SITE_URL") or "https://%s.github.io/%s/" % tuple(os.environ.get("GITHUB_REPOSITORY", "x/x").split("/"))
    for a in dados.get("alertas", []):
        if a["id"] in enviados:
            continue
        env = data_iso(a.get("enviado") or "")
        if env and (AGORA - env).total_seconds() > 3 * 3600:  # não avisa alerta antigo
            enviados.append(a["id"]); continue
        alvo = alvo_do_alerta(a, cidades)
        alvo = sorted(set(alvo))[:450]
        if not alvo:
            enviados.append(a["id"]); continue
        filtros = []
        for i in range(0, len(alvo), 50):
            if filtros:
                filtros.append({"operator": "OR"})
            filtros.append({"field": "tag", "key": "cidade", "relation": "in_array", "value": ",".join(alvo[i:i + 50])})
        corpo = {"app_id": app_id, "target_channel": "push", "filters": filtros, "url": site + "#traduzir",
                 "headings": {"en": "⚠️ Alerta da Defesa Civil para a sua região"},
                 "contents": {"en": "Toque para ver o que fazer."}}
        req = urllib.request.Request("https://api.onesignal.com/notifications", data=json.dumps(corpo).encode(),
                                     headers={"Content-Type": "application/json; charset=utf-8", "Authorization": "Key " + chave})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                print("aviso enviado:", a["id"], r.read()[:200])
            enviados.append(a["id"])
        except Exception as e:
            print("falha ao enviar aviso:", e)
    json.dump(enviados[-300:], open(os.path.join(OUT, "enviados.json"), "w"), ensure_ascii=False)


enviar_avisos()
salvar("alagamentos.json", "CGE, Prefeitura de São Paulo", alagamentos)

# ---------- Notícias recentes (manchetes do Google Notícias, só de veículos confiáveis; o app mostra título, fonte e link) ----------
from email.utils import parsedate_to_datetime
import urllib.parse
BUSCAS = ['"Defesa Civil" chuva "São Paulo"', 'alagamento OR deslizamento OR temporal "São Paulo"', '"onda de calor" "São Paulo"']
CONFIAVEIS = re.compile(r"g1|globo|cnn brasil|ag[êe]ncia sp|ag[êe]ncia brasil|folha|estad[ãa]o|uol|band|sbt|record|r7|cgesp|cge|climatempo|metsul|metr[óo]poles|poder360|veja|exame|terra|jovem pan|cbn|defesa civil|governo de s", re.I)


try:
    _nomes = sorted((c[0] for c in json.load(open("cidades-sp.json", encoding="utf-8")) if len(c[0]) > 4), key=len, reverse=True)
    CIDADE_RE = re.compile(r"\b(" + "|".join(re.escape(n) for n in _nomes) + r")\b", re.I)
except Exception:
    CIDADE_RE = re.compile(r"(?!x)x")


def categoria(t):
    if re.search(r"alerta", t, re.I): return "alerta"
    if re.search(r"calor|temperatura|quente", t, re.I): return "calor"
    if re.search(r"[áa]rvore|vento|temporal|granizo", t, re.I): return "arvore"
    return "chuva"


def noticias():
    achadas, vistos, amostra = [], set(), ""
    for q in BUSCAS:
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q + " when:7d", "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"})
        bruto = baixar(url, 25); amostra = amostra or bruto[:3000]
        for it in filhos(ET.fromstring(bruto.encode("utf-8")), "item"):
            titulo, link, fonte = texto(it, "title"), texto(it, "link"), texto(it, "source")
            if fonte and titulo.endswith(" - " + fonte):
                titulo = titulo[: -len(fonte) - 3]
            if not (titulo and link.startswith("https://") and fonte and CONFIAVEIS.search(fonte)):
                continue
            titulo = re.sub(r"(\s#\w+)+\s*$", "", titulo).strip()
            if not re.search(r"chuva|alag|desliz|enchente|inunda|temporal|defesa civil|calor|tempestade|[áa]rvore", titulo, re.I):
                continue
            if not (re.search(r"S[ãa]o Paulo|\bSP\b|paulist|capital", titulo, re.I) or CIDADE_RE.search(titulo)):
                continue  # só notícias de SP
            chave = re.sub(r"\W+", " ", titulo.lower())[:60]
            if chave in vistos:
                continue
            vistos.add(chave)
            try:
                dt = parsedate_to_datetime(texto(it, "pubdate"))
            except Exception:
                continue
            if (AGORA - dt).total_seconds() > 7 * 86400:
                continue
            achadas.append((dt, {"d": dt.astimezone(timezone(timedelta(hours=-3))).strftime("%d/%m/%Y"),
                                 "c": categoria(titulo), "v": fonte, "t": html.unescape(titulo)[:160], "u": link}))
    achadas.sort(key=lambda x: x[0], reverse=True)
    if not achadas:
        raise ValueError("nenhuma notícia recente de fonte confiável")
    return {"noticias": [n for _, n in achadas[:8]]}, amostra


salvar("noticias.json", "Google Notícias (manchetes de veículos confiáveis)", noticias)
