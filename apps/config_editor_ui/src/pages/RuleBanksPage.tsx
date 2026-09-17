import { useState } from 'react';
import { Badge, Button, Modal, TextArea, TextField } from '@adqm/gpb-ui';

import type { RuleBankSummary } from '../demo/model';
import { useWorkspace } from '../demo/workspace';

function emptyBank(): RuleBankSummary { return { id: '', description: '', columnRules: 0, codecRules: 0, indexRules: 0, orderByRules: 0, defaultFor: [] }; }

export function RuleBanksPage(): JSX.Element {
  const { ruleBanks, saveRuleBank, removeRuleBank } = useWorkspace();
  const [draft, setDraft] = useState<RuleBankSummary | null>(null);
  const [previousId, setPreviousId] = useState<string | undefined>();
  const open = (bank?: RuleBankSummary) => { setPreviousId(bank?.id); setDraft(bank ? { ...bank, defaultFor: [...bank.defaultFor] } : emptyBank()); };
  return <div className="page-stack">
    <div className="page-heading"><div><span className="eyebrow">Пространство поиска</span><h1>Банки правил</h1><p>Наборы типов, кодеков, индексов и вариантов ORDER BY для повторного использования.</p></div><Button variant="primary" onClick={() => open()}>Добавить банк</Button></div>
    <section className="rule-bank-grid">{ruleBanks.map((bank) => <article className="rule-bank-card" key={bank.id}>
      <div className="rule-bank-card-head"><div><Badge tone="info">ClickHouse</Badge><h2 className="mono">{bank.id}</h2></div><div className="table-actions"><Button variant="tertiary" onClick={() => open(bank)}>Изменить</Button><Button variant="danger" onClick={() => removeRuleBank(bank.id)}>Удалить</Button></div></div>
      <p>{bank.description}</p><div className="rule-counts"><div><strong>{bank.columnRules}</strong><span>правил типов</span></div><div><strong>{bank.codecRules}</strong><span>кодеков</span></div><div><strong>{bank.indexRules}</strong><span>индексов</span></div><div><strong>{bank.orderByRules}</strong><span>ORDER BY</span></div></div>
      <div className="card-footer-note">{bank.defaultFor.length ? `По умолчанию для: ${bank.defaultFor.join(', ')}` : 'Подключается явно в настройках бенчмарка'}</div>
    </article>)}</section>
    <Modal open={Boolean(draft)} onClose={() => setDraft(null)} title={previousId ? `Банк ${previousId}` : 'Новый банк правил'} footer={<><Button variant="secondary" onClick={() => setDraft(null)}>Отмена</Button><Button variant="primary" disabled={!draft?.id.trim()} onClick={() => { if (!draft) return; saveRuleBank(draft, previousId); setDraft(null); }}>Сохранить</Button></>}>
      {draft ? <div className="form-stack"><TextField label="Идентификатор" value={draft.id} onChange={(event) => setDraft({ ...draft, id: event.target.value })} /><TextArea label="Описание" rows={3} value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /><div className="form-grid"><TextField label="Правила типов" type="number" min={0} value={draft.columnRules} onChange={(event) => setDraft({ ...draft, columnRules: Number(event.target.value) })} /><TextField label="Правила кодеков" type="number" min={0} value={draft.codecRules} onChange={(event) => setDraft({ ...draft, codecRules: Number(event.target.value) })} /><TextField label="Правила индексов" type="number" min={0} value={draft.indexRules} onChange={(event) => setDraft({ ...draft, indexRules: Number(event.target.value) })} /><TextField label="Правила ORDER BY" type="number" min={0} value={draft.orderByRules} onChange={(event) => setDraft({ ...draft, orderByRules: Number(event.target.value) })} /></div><p className="field-help">Сейчас форма демонстрирует каталог банков. Полный редактор содержимого банка потребует зеркало `RuleBankConfig`, аналогичное редактору бенчмарка.</p></div> : null}
    </Modal>
  </div>;
}
