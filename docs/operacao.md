# Operação

## O que é gerado

Arquivo `sei_insights.xlsx` (ou o caminho de `--saida`) com **duas abas**:

- **Aba principal** — espelho do estado atual: **uma linha por processo**;
- **Resumo da última execução** — data/hora da execução, período pesquisado,
  visão geral (`Total de processos`, `Novos`) e contagens por situação e por
  status de coleta.

A planilha é **substituída a cada execução** (espelho do momento). Um resultado
vazio (0 processos) é válido: a aba principal sai vazia e o Resumo zerado, sem
erro.

> Todos os valores são gravados como **Texto** (formato `@`), para o Excel não
> interpretar `numero` (`21260.002715/2026-53` tem `.`, `/`, `-`), hashes ou links
> como número. As quantidades do Resumo restam números reais.

> **Onde ficou `data_execucao`?** Ela não se repete em cada linha: fica uma única
> vez na aba **Resumo**. No espelho SQLite ela continua em cada linha.

### As colunas da planilha

| Coluna | Explicação |
| ------ | ---------- |
| `numero` | Número **canônico** do processo (`NNNNN.NNNNNN/AAAA-NN`), lido do cabeçalho da página pública. É a chave primária no espelho SQLite. |
| `data_ultimo_despacho` | Data do último Despacho, da coluna **"Data de Inclusão"**. Vazia quando não há despacho público ou a data não foi exibida. |
| `situacao` | Situação classificada pelo motor de regras. Valores especiais: `Sem despacho público`, `Texto não extraível (digitalizado?)`, `Encerrado (verificar manualmente)`, fallback `Verificar manualmente`, `Em <destino>` (cabeçalho de sigla) e `Erro / retry`. |
| `destino` | Destinatário citado no cabeçalho (`Destino:` ou `À/Ao/Aos/Às <nome>`), mantido por extenso ou reduzido a sigla. Vários destinatários na mesma célula, separados por `"; "`. Vazio quando não envolve destinatário. |
| `acao_esperada` | Ação pedida pelo despacho (análise, assinatura, retorno, providências, ciência...). Vazia quando não se aplica. |
| `pendencia_curta` | Uma linha resumindo **quem está com o processo** e **o que falta**. Vazia quando não há pendência. |
| `status_coleta` | `concluído`, `concluído (cache)` ou `erro: <mensagem>`. |
| `hash_ultimo_despacho` | SHA-256 do identificador `número\|data` do último Despacho. Base do cache. |
| `link_process` | URL pública do processo (`md_pesq_processo_exibir.php?TOKEN`) — última coluna e identidade estável entre execuções. |

Como `situacao`, `destino`, `acao_esperada` e `pendencia_curta` são preenchidas:
veja [Regras e classificação](regras.md#de-onde-vem-cada-campo).

## Cache: por que um despacho novo é reanalisado

Para não repetir download/análise a cada execução, o programa guarda o
**identificador do último Despacho** (número documental + data) e grava o **hash
SHA-256** dele em `hash_ultimo_despacho`. No início de cada execução, o espelho
anterior é lido. Para cada processo:

- **sem cache ou com `--force`** → analisa do zero;
- **com cache e hash inalterado** → reaproveita a análise anterior (situação,
  destino, ação, pendência e data preservados) e marca `concluído (cache)`;
- **com cache e hash mudou** (novo Despacho) → **reanalisa**;
- **falha ao analisar** → gera `Erro / retry` com `status_coleta = erro: ...`,
  sem interromper os demais.

O hash é do **identificador do Despacho**, **não** do texto extraído. Um PDF
digitalizado (sem camada de texto) não "congela" o processo: se o Despacho mudar,
o identificador muda e o processo é reanalisado.

A linha anterior é localizada primeiro pelo **número** e, se não houver
correspondência, pela **URL** (`link_process`). Um processo é **"novo"** apenas
quando nunca foi visto antes (nem por número nem por URL).

> **Cache não verifica o arquivo em disco.** Com o hash inalterado, a análise é
> reaproveitada **sem conferir se o PDF ainda existe** em `downloads/`. Se os
> arquivos forem apagados à mão, a próxima execução continuará marcando
> `concluído (cache)`. Para forçar o download, rode `--force` (ou limpe o
> histórico).

> **Janela:** o espelho guarda apenas a última execução. Alternar a janela entre
> execuções (ex.: `--dias 7` ↔ `--dias 30`) pode sinalizar como "novos" processos
> já vistos antes — o efeito fica registrado no bloco **Visão geral** do Resumo.

## Como limpar os dados (ou reprocessar)

### Reprocessar tudo (`--force`)

```bash
python -m sei_insights --force
```

Nada é excluído: apenas força a reanálise; o espelho é reconstruído ao final.

### Apagar o histórico e recomeçar

Remove o banco espelho e os diagnósticos (`.state/`):

```powershell
# Windows (PowerShell)
Remove-Item -Recurse -Force .state
```

```cmd
:: Windows (Prompt de Comando)
rmdir /s /q .state
```

```bash
# Linux / macOS
rm -rf .state
```

Depois, execute `python -m sei_insights` novamente: todos os processos da janela
serão tratados como novos.

### Limpar com o cliente SQLite

```bash
sqlite3 .state/sei_insights.sqlite3
```

```sql
-- Processos e status
SELECT numero, situacao, status_coleta FROM processes ORDER BY numero;

-- Processos com pendência identificada
SELECT numero, situacao, pendencia_curta FROM processes WHERE pendencia_curta != '';

-- Zerar o espelho
DELETE FROM processes;
```

## Solução de problemas

Erros comuns e como resolvê-los estão no
[README](../README.md#solução-de-problemas-faq).
