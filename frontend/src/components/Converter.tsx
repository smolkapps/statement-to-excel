import { useCallback, useRef, useState } from "react";
import { useI18n } from "../i18n/I18nContext";
import {
  ApiError,
  convertStatement,
  type ConvertJsonResult,
  type OutputFormat,
  type RowFlag,
} from "../lib/api";
import { conversionLayout, track } from "../lib/analytics";
import { formatStatementMoney, reconciliationDifference, reconciliationStatus } from "../lib/reconciliation";

const CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CNY", "CHF", "CAD", "AUD"];

interface Props {
  accountId?: string;
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
    setResult(null);
    setDownload(null);
    setError(null);
    setFile(null);
    if (selected && !/\.pdf$/i.test(selected.name)) {
      setError(t.convert_error_file_type);
      return;
    }
    if (selected?.size === 0) {
      setError(t.convert_error_file_empty);
      return;
    }
    if (selected && selected.size > 20 * 1024 * 1024) {
      setError(t.convert_error_file_size);
      return;
    }
    setFile(selected);
    if (selected) track("file-selected");
  }, [t]);

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
      const status = reconciliationStatus(result.reconciliation);
      track("convert-success", {
        balanced: status === "balanced" ? "yes" : status === "not_balanced" ? "no" : "unknown",
        layout: conversionLayout(result.layout),
      });
      if (result.charge && result.charge.metered !== false) {
        onCharged?.(result.charge.pages);
      }
      if (blob) {
        setDownload({ blob, filename });
        triggerDownload(blob, filename);
      }
    } catch (err) {
      track("convert-error");
      if (err instanceof ApiError && err.kind === "billing_hold") {
        setError(t.billing_hold);
      } else if (err instanceof ApiError && err.kind === "insufficient") {
        setError(t.convert_error_insufficient);
      } else if (err instanceof ApiError && err.status === 504) {
        setError(t.convert_error_timeout);
      } else if (err instanceof ApiError && (err.status === 409 || (err.status !== undefined && err.status >= 500))) {
        setError(t.convert_error_generic);
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
      <details className="conversion-limits">
        <summary>{t.convert_limits_title}</summary>
        <p>{t.convert_limits_body}</p>
        <a href="#privacy">{t.privacy_title}</a>
      </details>

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
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            if (!pendingRef.current) inputRef.current?.click();
          }
        }}
        aria-label={t.convert_drop}
      >
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          hidden
          disabled={busy}
          onChange={(e) => {
            selectFile(e.target.files?.[0] ?? null);
            e.target.value = "";
          }}
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
  const { t, locale } = useI18n();
  const s = result.summary;
  const reconciliation = result.reconciliation;
  const status = reconciliationStatus(reconciliation);
  const money = (value: string) => formatStatementMoney(value, s.currency, locale);
  // Match the reconciliation's decimal conventions without changing the exact
  // values or adding currency symbols to the existing table and summary cells.
  const number = (value: string) => {
    const [integer, fraction = ""] = value.split(".");
    const precision = Math.max(2, fraction.length);
    const whole = BigInt(integer);
    const amount = value.startsWith("-") && whole === 0n ? -0 : whole;
    return new Intl.NumberFormat(locale, {
      minimumFractionDigits: precision, maximumFractionDigits: precision,
    }).formatToParts(amount)
      .map((part) => part.type === "fraction" ? fraction.padEnd(precision, "0") : part.value).join("");
  };
  let statusLine = t.reconciliation_cannot_check;
  if (reconciliation && status === "balanced") {
    const template = reconciliation.account_type === "card"
      ? t.reconciliation_balanced_card : t.reconciliation_balanced_deposit;
    statusLine = template.replace(/\{(\w+)\}/g, (_, key: string) =>
      money(reconciliation.terms[key as keyof typeof reconciliation.terms]!));
  } else if (reconciliation && status === "not_balanced") {
    statusLine = t.reconciliation_not_balanced.replace("{difference}", money(reconciliationDifference(reconciliation)!));
  }
  const flagLabels: Record<RowFlag, string> = {
    year_inferred_rollover: t.row_flag_year_inferred_rollover,
    sign_from_balance: t.row_flag_sign_from_balance,
    multiline_description: t.row_flag_multiline_description,
  };
  const rowNotes = new Map<number, string>();
  if (status === "not_balanced" && Array.isArray(reconciliation?.row_flags)) {
    for (const row of reconciliation.row_flags) {
      if (!row || !Number.isInteger(row.row_index) || !Array.isArray(row.flags)) continue;
      const note = row.flags.map((flag) => flagLabels[flag]).filter(Boolean).join(" ");
      if (note) rowNotes.set(row.row_index, note);
    }
  }
  // Include later suspect rows as well as the usual first 50, retaining the
  // original row index so a warning remains useful for multi-page statements.
  const previewRows = result.transactions.map((row, index) => ({ row, index }))
    .filter(({ index }) => index < 50 || rowNotes.has(index));
  return (
    <div className="results">
      <p className={`reconciliation-status ${status}`} role="status" data-status={status}>{statusLine}</p>
      <div className="summary-strip">
        <span>
          <strong>{s.count}</strong> {t.summary_count}
        </span>
        <span>
          {t.summary_debit}: <strong>{number(s.total_debit)}</strong>
        </span>
        <span>
          {t.summary_credit}: <strong>{number(s.total_credit)}</strong>
        </span>
        <span>
          {t.summary_net}: <strong>{number(s.net)}</strong>
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
            {previewRows.map(({ row, index: i }) => (
              <tr key={i} className={rowNotes.has(i) ? "flagged-row" : undefined} title={rowNotes.get(i)}>
                <td>{row.date}</td>
                <td>
                  {row.description}
                  {rowNotes.has(i) && <small className="row-flag-note">{rowNotes.get(i)}</small>}
                </td>
                <td className={`num ${row.type}`}>{number(row.amount)}</td>
                <td className="num">{row.balance === null ? "" : number(row.balance)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
