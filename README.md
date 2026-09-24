# SEI Insights

Standalone Python tool that discovers public SEI/ColaboraGov processes for a given unit and period, reads the most recent "Despacho" text, classifies situation/pendency with local rules, and writes a mirror spreadsheet (SQLite = exact copy).

## Install

```bash
pip install -r requirements.txt
playwright install chromium
```

## Usage

```bash
python main.py [options]
```

### Options

- `--orgao` - Organization name (default: `MMulheres`)
- `--unidade` - Unit name (default: `MMULHERES-SE-SGA-CGATI-CTI-DTI`)
- `--dias` - Lookback window in days (default: `7`)
- `--inicio` - Start date (DD/MM/YYYY), overrides `--dias`
- `--fim` - End date (DD/MM/YYYY), defaults to today
- `--manual-captcha` - Pause for manual CAPTCHA solving
- `--min-delay` - Minimum delay between requests in seconds (default: `2.0`)
- `--max-delay` - Maximum delay between requests in seconds (default: `5.0`)
- `--force` - Force re-analysis of cached processes
- `--saida` - Output XLSX file path (default: `sei_insights.xlsx`)

## CAPTCHA

By default uses OCR (ddddocr) to solve CAPTCHAs automatically. Use `--manual-captcha` to pause and solve manually.

## Output

- **XLSX spreadsheet** (`sei_insights.xlsx` by default) with three tabs:
  - **Aba principal** - All processes (mirror of SQLite)
  - **Novos** - Newly discovered processes in this run
  - **Resumo** - Counts by situation and collection status
- **SQLite mirror** (`.state/sei_insights.sqlite3`) - Exact copy of the spreadsheet rows, rebuilt each successful run

## Cache

Cache key is the **last Despacho identifier** (document number + date), not the extracted text. This means scanned PDFs (no text layer) won't freeze the process - it will be re-analyzed on next run if the identifier changes.

## Rules

Classification rules are in `regras.json` (ordered list with regex patterns + fallback). Adjust without touching code.

## Development

```bash
# Run all tests
python -m unittest discover -s tests -v

# Run specific test module
python -m unittest tests.test_utils -v
```