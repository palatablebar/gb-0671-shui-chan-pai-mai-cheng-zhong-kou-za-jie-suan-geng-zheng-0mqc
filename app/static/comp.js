const feedback = document.querySelector('#feedback');
async function request(url, body, method = 'POST') {
  const r = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: method === 'GET' ? undefined : JSON.stringify(body || {}) });
  const data = await r.json();
  if (!r.ok) throw Error(data.detail || '操作失败，请重试');
  return data;
}
function goto(runId) {
  const url = new URL(location.href);
  url.searchParams.set('run_id', runId);
  location.href = url;
}
const rerunBtn = document.querySelector('#comp-run');
if (rerunBtn) rerunBtn.addEventListener('click', async () => {
  rerunBtn.disabled = true;
  feedback.textContent = '重跑中…';
  try {
    const data = await request('/api/comp/runs/' + document.body.dataset.runId + '/rerun', {});
    feedback.textContent = `批次 ${data.manifest.run_id} 不变 · 垫付 ${data.comp_summary.advanced} CNY`;
    goto(data.manifest.run_id);
  } catch (e) { feedback.textContent = e.message; } finally { rerunBtn.disabled = false; }
});
const publish = document.querySelector('#publish');
if (publish) publish.addEventListener('click', async () => {
  try {
    const seal = await request('/api/comp/runs/' + publish.dataset.id + '/publish', {});
    feedback.textContent = `封存生效：${seal.seal_id}`;
    location.href = '/comp-seals?run_id=' + publish.dataset.id;
  } catch (e) { feedback.textContent = e.message; }
});
const review = document.querySelector('#review');
if (review) review.addEventListener('click', async () => {
  try {
    const run = await request('/api/comp/runs/' + review.dataset.id, {}, 'GET');
    const result = await request('/api/comp/runs/' + review.dataset.id + '/review', { revision: run.revision });
    feedback.textContent = '复核状态：' + result.status;
    goto(result.manifest.run_id);
  } catch (e) { feedback.textContent = e.message; }
});
const filter = document.querySelector('#filter');
if (filter) filter.addEventListener('input', e => {
  const text = e.target.value.trim();
  document.querySelectorAll('.primary-panel tbody tr').forEach(row => { row.hidden = !row.textContent.includes(text); });
});
const datasetSel = document.querySelector('#dataset');
if (datasetSel) datasetSel.addEventListener('change', async e => {
  try {
    const data = await request('/api/comp/runs', { dataset: e.target.value });
    goto(data.manifest.run_id);
  } catch (err) { feedback.textContent = err.message; }
});
document.querySelectorAll('.rollback').forEach(btn => btn.addEventListener('click', async () => {
  try {
    const seal = await request('/api/comp/seals/' + btn.dataset.seal + '/rollback', {});
    feedback.textContent = `已恢复旧版：${seal.seal_id}`;
    location.reload();
  } catch (e) { feedback.textContent = e.message; }
}));
const filePickers = document.querySelectorAll('.csv-file');
if (filePickers.length) {
  filePickers.forEach(picker => picker.addEventListener('change', async () => {
    const file = picker.files[0];
    if (!file) return;
    if (file.size > 2000000) { alert('文件超过2MB'); return; }
    const editor = document.querySelector(`.csv-text[data-table="${picker.dataset.table}"]`);
    const bytes = await file.arrayBuffer();
    try { editor.value = new TextDecoder('utf-8', { fatal: true }).decode(bytes); }
    catch (e) { editor.value = new TextDecoder('gb18030', { fatal: true }).decode(bytes); }
  }));
  document.querySelector('#import-csv').addEventListener('click', async event => {
    event.target.disabled = true;
    const tables = {};
    document.querySelectorAll('.csv-text').forEach(t => { if (t.value.trim()) tables[t.dataset.table] = t.value; });
    try {
      const data = await request('/api/comp/runs', { tables });
      goto(data.manifest.run_id);
    } catch (e) { feedback.textContent = e.message; } finally { event.target.disabled = false; }
  });
}
