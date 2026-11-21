const notice = document.getElementById('p-notice');

function valueOrNull(elementId) {
  const element = document.getElementById(elementId);
  const text = element.value.trim();
  return text === '' ? null : text;
}

function postJson(path, payload) {
  return fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(async (response) => {
    const body = await response.json();
    if (!response.ok) throw new Error(body.message || '操作失败');
    return body;
  });
}

document.getElementById('p-confirm').addEventListener('click', async () => {
  const payload = {
    claim_id: valueOrNull('p-claim'),
    period: valueOrNull('p-period'),
    item: valueOrNull('p-item'),
    confirmed_qty: valueOrNull('p-qty'),
    provisional_price: valueOrNull('p-price'),
    run_id: valueOrNull('p-run'),
  };
  if (!payload.claim_id || !payload.period) {
    notice.textContent = '申报编号和周期为必填。';
    return;
  }
  notice.textContent = '签认中…';
  try {
    await postJson('/api/provisional', payload);
    window.location.reload();
  } catch (error) {
    notice.textContent = error.message;
  }
});

document.querySelectorAll('.a-submit').forEach((button) => {
  button.addEventListener('click', async () => {
    const key = button.dataset.key;
    const price = document.querySelector(`.a-price[data-key="${CSS.escape(key)}"]`).value.trim();
    const ref = document.querySelector(`.a-ref[data-key="${CSS.escape(key)}"]`).value.trim();
    if (!price || !ref) {
      notice.textContent = '批准单价和批价文号为必填。';
      return;
    }
    notice.textContent = '批价入账中…';
    try {
      await postJson(`/api/provisional/${encodeURIComponent(key)}/approval`, {
        version: Number(button.dataset.version),
        approved_price: price,
        approval_ref: ref,
      });
      window.location.reload();
    } catch (error) {
      notice.textContent = error.message;
    }
  });
});
