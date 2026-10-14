import { CircleMarker, MapContainer, TileLayer, Tooltip } from "react-leaflet";
import type { MapZip } from "../api";
import { changeColor, money, num, pct } from "../lib/format";

export default function ZipMap({ zips, unit, height = 420 }: { zips: MapZip[]; unit: string; height?: number }) {
  const maxActive = Math.max(1, ...zips.map((z) => z.end_active ?? 0));
  const ordered = [...zips].sort((a, b) => Number(a.in_scope) - Number(b.in_scope));
  return (
    <div className="relative">
      <MapContainer center={[32.86, -96.8]} zoom={9} scrollWheelZoom={false} style={{ height }}>
        <TileLayer
          attribution="Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors"
          url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"
          maxZoom={16}
        />
        <TileLayer
          url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}"
          maxZoom={16}
          zIndex={650}
        />
        {ordered.map((z) => {
          const scoped = z.in_scope;
          const r = scoped ? 5 + 13 * Math.sqrt((z.end_active ?? 0) / maxActive) : 3;
          return (
            <CircleMarker
              key={z.zipcode}
              center={[z.lat, z.lon]}
              radius={r}
              pathOptions={{
                color: z.added ? "#f59e0b" : scoped ? "#ffffff" : "#94a3b8",
                weight: z.added ? 3 : scoped ? 1.5 : 1,
                fillColor: scoped ? changeColor(z.change_pct) : "#cbd5e1",
                fillOpacity: scoped ? 0.9 : 0.4,
              }}
            >
              <Tooltip direction="top" offset={[0, -4]}>
                <div className="text-xs">
                  <div className="font-semibold">
                    {z.zipcode} · {z.neighborhood ?? z.city}
                    {z.added && <span className="ml-1 text-amber-600">(added by feedback loop)</span>}
                  </div>
                  <div className="text-slate-500">{z.price_tier} tier · {z.distance_mi} mi from downtown</div>
                  {scoped && z.change_pct != null && (
                    <div className="mt-1">
                      12-mo change <b>{pct(z.change_pct)}</b> · end median <b>{money(z.end_price, unit, true)}</b> · {num(z.end_active)} active
                    </div>
                  )}
                  {!scoped && <div className="mt-1 text-slate-400">Outside the current criteria</div>}
                </div>
              </Tooltip>
            </CircleMarker>
          );
        })}
      </MapContainer>
      <div className="pointer-events-none absolute bottom-3 left-3 z-[400] rounded-lg bg-white/90 px-3 py-2 text-[11px] shadow">
        <div className="mb-1 font-semibold text-slate-700">12-month change in median list price</div>
        <div className="flex items-center gap-1">
          <span>-12%</span>
          <div className="h-2 w-28 rounded-full" style={{ background: "linear-gradient(90deg,#f43f5e,#fecdd3,#d1fae5,#10b981)" }} />
          <span>+12%</span>
        </div>
        <div className="mt-1 text-slate-500">Size = active listings · <span className="text-amber-600">amber ring</span> = added by feedback loop</div>
      </div>
    </div>
  );
}
