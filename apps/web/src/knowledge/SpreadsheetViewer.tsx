// Full-width, read-only spreadsheet viewer for csv/xlsx documents, backed by Univer. Univer itself
// (~heavy) is loaded on demand via dynamic import() so it never lands in the main bundle — only paid
// for when someone actually opens a sheet.
import { useEffect, useRef, useState } from "react";
import { api, errMsg } from "../api";
import type { Doc } from "./shared";

interface RowsResponse { columns: string[]; rows: (string | number | boolean | null)[][]; total: number; truncated: boolean }
type CellValue = string | number | boolean;

export function SpreadsheetViewer({ doc, onClose }: { doc: Doc; onClose: () => void }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const disposeRef = useRef<(() => void) | null>(null);
  const [err, setErr] = useState("");
  const [meta, setMeta] = useState<{ total: number; truncated: boolean; shown: number } | null>(null);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      let data: RowsResponse;
      try {
        data = await api<RowsResponse>(`/api/datasets/${doc.document_id}/rows?limit=500`);
      } catch (e) {
        if (!cancelled) setErr(errMsg(e));
        return;
      }
      if (cancelled) return;
      setMeta({ total: data.total, truncated: data.truncated, shown: data.rows.length });
      const el = containerRef.current;
      if (!el) return;
      try {
        const [{ createUniver, LocaleType }, { UniverSheetsCorePreset }, esESModule] = await Promise.all([
          import("@univerjs/presets"),
          import("@univerjs/preset-sheets-core"),
          import("@univerjs/preset-sheets-core/locales/es-ES"),
        ]);
        await import("@univerjs/preset-sheets-core/lib/index.css");
        if (cancelled || !containerRef.current) return;
        const cellData: Record<number, Record<number, { v: CellValue }>> = { 0: {} };
        data.columns.forEach((c, i) => { cellData[0][i] = { v: c }; });
        data.rows.forEach((row, ri) => {
          cellData[ri + 1] = {};
          row.forEach((v, ci) => { cellData[ri + 1][ci] = { v: v ?? "" }; });
        });
        const { univer, univerAPI } = createUniver({
          locale: LocaleType.ES_ES,
          locales: { [LocaleType.ES_ES]: esESModule.default },
          darkMode: true,
          presets: [UniverSheetsCorePreset({
            container: containerRef.current, header: false, toolbar: false, footer: false, formulaBar: false, contextMenu: false,
          })],
        });
        const wb = univerAPI.createWorkbook({
          id: `alice-dataset-${doc.document_id}`, name: doc.original_name, sheetOrder: ["s1"],
          sheets: { s1: { id: "s1", name: "Datos", cellData, rowCount: data.rows.length + 1, columnCount: Math.max(1, data.columns.length) } },
        });
        wb.setEditable(false);
        disposeRef.current = () => univer.dispose();
      } catch (e) {
        if (!cancelled) setErr(errMsg(e));
      }
    })();
    return () => { cancelled = true; disposeRef.current?.(); disposeRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc.document_id]);

  return (
    <div className="sheet-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="sheet-modal" role="dialog" aria-modal="true" aria-label={`Planilla de ${doc.original_name}`}>
        <div className="row wrap between sheet-modal-head">
          <h3>{doc.original_name}</h3>
          <div className="row" style={{ alignItems: "center" }}>
            {meta && (
              <span className="muted small-text">
                {meta.truncated ? `Mostrando ${meta.shown} de ${meta.total} filas` : `${meta.total} fila${meta.total === 1 ? "" : "s"}`}
              </span>
            )}
            <button ref={closeRef} className="ghost small" onClick={onClose} aria-label="Cerrar planilla">Cerrar</button>
          </div>
        </div>
        {err ? <p className="error" role="alert">{err}</p> : <div className="sheet-paper" ref={containerRef} />}
      </div>
    </div>
  );
}
