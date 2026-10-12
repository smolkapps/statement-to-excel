import { useCallback, useRef, useState } from "react";
import { useI18n } from "../i18n/I18nContext";
import {
  ApiError,
  convertStatement,
  type ConvertJsonResult,
  type OutputFormat,
} from "../lib/api";
import { track } from "../lib/analytics";

const CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CNY", "CHF", "CAD", "AUD"];

interface Props {
  accountId: string;
  onCharged?: (pages: number) => void;
}

export function Converter({ accountId, onCharged }: Props) {
  const { t } = useI18n();
  const [file, setFile] = useState<File | null>(null);
  const [fmt, setFmt] = useState<OutputFormat>("xlsx");
  const [currency, setCurrency] = useState("USD");
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ConvertJsonResult | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const pendingRef = useRef(false);
  const [download, setDownload] = useState<{ blob: Blob; filename: string } | null>(null);

  const selectFile = useCallback((selected: File | null) => {
    if (pendingRef.current) return;
    setFile(selected);
    setResult(null);
    setDownload(null);
    setError(null);
    if (selected) track("file-selected");
  }, []);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const selected = e.dataTransfer.files?.[0];
    if (selected) selectFile(selected);
  }, [selectFile]);

  const triggerDownload = (blob: Blob, name: string) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  const handleConvert = async () => {
    if (!file || pendingRef.current) return;
    pendingRef.current = true;
    setBusy(true);
    setError(null);
    setResult(null);
    setDownload(null);
    try {
      // ONE metered call returns the preview rows and (for binary formats)
      // the file itself, so a conversion is charged exactly once.
      const { result, blob, filename } = await convertStatement(file, {
        accountId,
        fmt,
        currency,
      });
      setResult(result);
      track("convert-success");
      onCharged?.(result.charge?.pages ?? 1);
      if (blob) {
        setDownload({ blob, filename });
        triggerDownload(blob, filename);
      }
    } catch (err) {
      track("convert-error");
      if (err instanceof ApiError && err.kind === "insufficient") {
        setError(t.convert_error_insufficient);
      } else if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError(t.convert_error_generic);
      }
    } finally {
      pendingRef.current = false;
      setBusy(false);
    }
  };

  return (
    <section className="converter" id="convert">
      <h2>{t.convert_title}</h2>

      <div
        className={`dropzone${dragging ? " dragging" : ""}${file ? " has-file" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => !pendingRef.current && inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
        }}
        aria-label={t.convert_drop}
      >
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          hidden
          disabled={busy}
          onChange={(e) => selectFile(e.target.files?.[0] ?? null)}
        />
        <div className="dropzone-inner">
          <span className="dropzone-icon" aria-hidden="true">
            📄
          </span>
          <p className="dropzone-label">{file ? file.name : t.convert_drop}</p>
          <p className="dropzone-hint">{t.convert_drop_hint}</p>
        </div>
      </div>

      <div className="convert-controls">
        <label>
          {t.convert_format}
          <select
            value={fmt}
            disabled={busy}
            onChange={(e) => setFmt(e.target.value as OutputFormat)}
          >
            <option value="xlsx">Excel (.xlsx)</option>
            <option value="csv">CSV</option>
            <option value="json">JSON</option>
          </select>
        </label>
        <label>
          {t.convert_currency}
          <select value={currency} disabled={busy} onChange={(e) => setCurrency(e.target.value)}>
            {CURRENCIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <button
          className="btn btn-primary"
          disabled={!file || busy}
          onClick={handleConvert}
        >
          {busy ? t.convert_processing : t.convert_button}
        </button>
      </div>

      {error && (
        <p className="convert-error" role="alert">
          {error}
        </p>
      )}

      {download && (
        <button className="btn btn-outline" onClick={() => triggerDownload(download.blob, download.filename)}>
          {t.convert_download}
        </button>
      )}
      {result && <ResultsTable result={result} />}
    </section>
  );
}

function ResultsTable({ result }: { result: ConvertJsonResult }) {
  const { t } = useI18n();
  const s = result.summary;
  return (
    <div className="results">
      <div className="summary-strip">
        <span>
          <strong>{s.count}</strong> {t.summary_count}
        </span>
        <span>
          {t.summary_debit}: <strong>{s.total_debit}</strong>
        </span>
        <span>
          {t.summary_credit}: <strong>{s.total_credit}</strong>
        </span>
        <span>
          {t.summary_net}: <strong>{s.net}</strong>
        </span>
      </div>
      <h3>{t.convert_results_title}</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t.col_date}</th>
              <th>{t.col_description}</th>
              <th className="num">{t.col_amount}</th>
              <th className="num">{t.col_balance}</th>
            </tr>
          </thead>
          <tbody>
            {result.transactions.slice(0, 50).map((row, i) => (
              <tr key={i}>
                <td>{row.date}</td>
                <td>{row.description}</td>
                <td className={`num ${row.type}`}>{row.amount}</td>
                <td className="num">{row.balance ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
