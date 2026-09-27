import html
import json
from urllib.parse import quote

from .config import MONTH_NAMES
from .map_model import month_display_title
from .models import jsonable


LEAFLET_HEAD = '''
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css">
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css">
'''
LEAFLET_SCRIPTS = '''
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
'''
STYLE = '''
:root{font-family:Segoe UI,system-ui,sans-serif;color:#17212b;background:#edf1f4}*{box-sizing:border-box}body{margin:0}header,main{max-width:1180px;margin:auto;padding:24px}header{padding-bottom:8px}h1{font-size:30px;margin:4px 0}h2{font-size:19px}.muted{color:#5e6b76}.stats{display:flex;gap:22px;flex-wrap:wrap;margin:16px 0}.stats strong{display:block;font-size:24px}.panel{background:#fff;border:1px solid #d8dee4;border-radius:8px;padding:18px;margin:16px 0}#map{height:560px;border:1px solid #ccd4db;border-radius:6px}.filters{display:flex;gap:7px;flex-wrap:wrap;margin:10px 0}.filters button{border:1px solid #aeb9c2;background:#fff;border-radius:5px;padding:7px 11px;cursor:pointer}.filters button.active{background:#185b78;color:#fff}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}.month{border-top:3px solid #2b718f}.month a{color:#185b78;font-weight:700}.places{padding-left:20px}.fallback{font:13px ui-monospace,monospace;max-height:180px;overflow:auto}a{color:#185b78}@media(max-width:700px){#map{height:420px}header,main{padding:16px}}
'''


def _embedded(value):
    return json.dumps(jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).replace("<", "\\u003c")


def _shell(title, body, data, script=""):
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>{LEAFLET_HEAD}<style>{STYLE}</style></head><body>{body}<script id="geo-data" type="application/json">{_embedded(data)}</script>{LEAFLET_SCRIPTS}<script>{script}</script></body></html>'''


COMMON_JS = r'''
const data=JSON.parse(document.getElementById('geo-data').textContent);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function makeMap(events, filterKey, sequences=[]){
 if(!events.length||typeof L==='undefined')return;
 const map=L.map('map'); L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap'}).addTo(map);
 let layer=typeof L.markerClusterGroup==='function'?L.markerClusterGroup():L.layerGroup(); layer.addTo(map);
 function draw(value){layer.clearLayers();const shown=events.filter(e=>!value||String(e[filterKey])===String(value));const pts=[];
 shown.forEach(e=>{const p=[e.latitude,e.longitude];pts.push(p);const alt=e.altitude_m==null?'':`<br>Altitude: ${Math.round(e.altitude_m).toLocaleString()} m`;L.marker(p).bindPopup(`${esc(e.date)}<br>${esc(e.filename)}${alt}`).addTo(layer)});
 const ids=new Set(shown.map(e=>e.event_id));const byId=Object.fromEntries(events.map(e=>[e.event_id,e]));sequences.forEach(s=>{const line=s.event_ids.filter(id=>ids.has(id)).map(id=>[byId[id].latitude,byId[id].longitude]);if(line.length>1)L.polyline(line,{color:'#2b718f',weight:2,opacity:.65,dashArray:'5 5'}).bindTooltip('Photo sequence').addTo(layer)});
 if(pts.length===1)map.setView(pts[0],11);else if(pts.length)map.fitBounds(pts,{padding:[24,24]});}
 draw(null);document.querySelectorAll('[data-filter]').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('[data-filter]').forEach(x=>x.classList.remove('active'));b.classList.add('active');draw(b.dataset.filter||null)}));
}
'''


def render_month(model):
    title = month_display_title(model)
    notes = f'<section class="panel"><h2>Notes</h2>{model.human_notes.safe_html}</section>' if model.human_notes and model.human_notes.safe_html else ""
    human_places = ""
    if model.human_notes and model.human_notes.places:
        human_places = '<p><strong>Places noted by you:</strong> ' + ", ".join(html.escape(p) for p in model.human_notes.places) + "</p>"
    derived = [cluster for cluster in model.clusters if cluster.place_name]
    place_list = "".join(f"<li>{html.escape(c.place_name)}" + (f", {html.escape(c.admin1)}" if c.admin1 else "") + (f", {html.escape(c.country)}" if c.country else "") + f" - {len(c.event_ids)} event(s)</li>" for c in derived)
    filters = '<div class="filters"><button class="active" data-filter="">All</button>' + "".join(
        f'<button data-filter="{group.date.isoformat()}">{group.date.day:02d}</button>' for group in model.day_groups) + "</div>"
    if model.geo_events:
        map_section = f'<section class="panel"><h2>Memory map</h2>{filters}<div id="map"></div><p class="muted">Photo sequence lines represent capture order, not a traveled route. Map tiles require Internet access; event data remains embedded in this file.</p></section>'
    else:
        map_section = f'<section class="panel"><h2>No GPS-tagged photographs were found</h2><p>{model.total_media_examined} media files were examined. Notes and folder context are still shown below.</p></section>'
    fallback = "".join(f"<li>{e.resolved_date.isoformat()} - {html.escape(e.filename)} - {e.latitude:.6f}, {e.longitude:.6f}</li>" for e in model.geo_events)
    body = f'''<header><div class="muted">LOCAL PHOTO ARCHIVE</div><h1>{html.escape(title)}</h1><div class="stats"><div><strong>{model.total_media_examined}</strong>media files examined</div><div><strong>{len(model.geo_events)}</strong>geotagged photo events</div><div><strong>{len(model.day_groups)}</strong>days with GPS</div><div><strong>{len(model.clusters)}</strong>location clusters</div></div>{human_places}</header><main>{map_section}{notes}<section class="panel"><h2>Locations</h2>{f'<ul class="places">{place_list}</ul>' if place_list else '<p class="muted">No derived place names are available.</p>'}<details><summary>Embedded GPS event list</summary><ul class="fallback">{fallback}</ul></details></section></main>'''
    payload = {"events": [{**jsonable(e), "date": e.resolved_date.isoformat()} for e in model.geo_events],
               "sequences": [sequence for group in model.day_groups for sequence in jsonable(group.sequences)], "model": model}
    return _shell(title, body, payload, COMMON_JS + "makeMap(data.events,'date',data.sequences);")


def render_year(model):
    title = f"{model.year} - Travel & Photo Map"
    notes = f'<section class="panel"><h2>Year notes</h2>{model.human_notes.safe_html}</section>' if model.human_notes and model.human_notes.safe_html else ""
    cards = []
    for month in model.months:
        human = ", ".join(html.escape(p) for p in month.human_place_labels)
        derived = ", ".join(html.escape(p) for p in month.derived_place_labels)
        detail = "".join(x for x in [f"<p>{html.escape(month.notes_excerpt)}</p>" if month.notes_excerpt else "",
                                      f"<p><strong>Human labels:</strong> {human}</p>" if human else "",
                                      f"<p><strong>Derived places:</strong> {derived}</p>" if derived else ""])
        href = quote(month.relative_html_path.replace("\\", "/"), safe="/")
        cards.append(f'<article class="panel month"><h2>{html.escape(month.display_title)}</h2><p>{month.total_media_examined} media files · {month.gps_day_count} GPS days · {month.geo_event_count} events</p>{detail}<a href="{href}">Open {MONTH_NAMES[month.month]}</a></article>')
    filters = '<div class="filters"><button class="active" data-filter="">All</button>' + "".join(
        f'<button data-filter="{m.month}">{MONTH_NAMES[m.month]}</button>' for m in model.months if m.geo_event_count) + "</div>"
    map_section = f'<section class="panel"><h2>Year map</h2>{filters}<div id="map"></div><p class="muted">Map tiles require Internet access; month navigation and embedded event data remain available offline.</p></section>' if model.geo_events else '<section class="panel"><h2>No GPS-tagged photographs were found this year</h2><p>The month chronology remains available.</p></section>'
    body = f'''<header><div class="muted">ANNUAL PHOTO ARCHIVE</div><h1>{html.escape(title)}</h1><div class="stats"><div><strong>{len(model.months)}</strong>months with photos</div><div><strong>{sum(m.geo_event_count>0 for m in model.months)}</strong>months with GPS</div><div><strong>{len(model.geo_events)}</strong>geotagged photo events</div></div></header><main>{notes}{map_section}<section><h2>Months</h2><div class="grid">{''.join(cards)}</div></section></main>'''
    events = [{**jsonable(event),
               "month": next((month.month for month in model.months if month.source_folder_name in event.representative_path.parts), event.resolved_date.month),
               "date": event.resolved_date.isoformat()} for event in model.geo_events]
    return _shell(title, body, {"events": events, "model": model}, COMMON_JS + "makeMap(data.events,'month');")
