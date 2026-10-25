import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';
import path from 'path';

test.describe.configure({ mode: 'serial' });
test.skip(process.env.BLUE_LIVE_E2E !== '1', 'Requires BLUE_LIVE_E2E=1 and isolated PostgreSQL/API/Gemini.');

const projectRoot = path.resolve(process.cwd(), '..');

function runDbHelper(cmd: string, arg = ''): string {
  const fullCmd = `python scripts/db_test_helper.py ${cmd} ${arg}`.trim();
  return execSync(fullCmd, { cwd: projectRoot, encoding: 'utf-8' });
}

test.beforeAll(() => {
  // Clean PostgreSQL database before live tests
  runDbHelper('clean');
});

test('1. Live Empty State displays honest empty workspace without mock data', async ({ page }) => {
  // Configure browser to use live API mode
  await page.addInitScript(() => {
    localStorage.setItem(
      'blue.settings.v1',
      JSON.stringify({ mode: 'api', baseUrl: '', polling: false })
    );
  });

  await page.goto('/');
  await expect(page.locator('.brand-intro')).not.toBeAttached();

  // Header must display live data pill
  await expect(page.locator('.header-tools .source-pill')).toHaveText('Рабочие данные');

  // Stats should reflect 0 messages
  await expect(page.locator('.inbox-title')).toContainText('0 сообщений');
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(0);
  await expect(page.locator('.empty-state')).toBeVisible();
  await expect(page.locator('.empty-state')).toContainText('Сообщений не найдено');
});

test('2. Live Ingestion: POST /api/messages creates PENDING alert in browser', async ({ page, request }) => {
  await page.addInitScript(() => {
    localStorage.setItem(
      'blue.settings.v1',
      JSON.stringify({ mode: 'api', baseUrl: '', polling: false })
    );
  });

  // Post a synthetic suspicious message to FastAPI backend
  const res = await request.post('http://127.0.0.1:8000/api/messages', {
    data: {
      platform: 'telegram',
      chat_id: 'live_test_chat_kz',
      chat_name: 'Live Chat KZ',
      message_id: 'msg_live_001',
      sender_hash: 'sender_live_001',
      text: 'Срочно вложи 30 000 тг и получи 300 000 за неделю! Перевод на карту Kaspi: +7 701 999-88-77. Только сегодня!',
      timestamp: new Date().toISOString()
    }
  });
  expect(res.status()).toBe(200);
  const data = await res.json();
  expect(data.status).toBe('PENDING');
  const alertId = data.id;

  // Open browser and verify message in inbox
  await page.goto('/');
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(1);
  await expect(page.locator('.alerts-table')).toContainText('Live Chat KZ');
  await expect(page.locator('.alerts-table')).toContainText('В очереди');

  // Open alert details
  await page.getByRole('link', { name: `Открыть сообщение ${alertId}` }).click();
  await expect(page.locator('.page-heading h1')).toContainText('Проверка сообщения');
  await expect(page.locator('.score-number')).toContainText('—');
  await expect(page.locator('.form-caption')).toContainText('Дождитесь успешного анализа сообщения.');

  // Verify review button is disabled in PENDING status
  await expect(page.locator('.review-form button')).toBeDisabled();
});

test('3. Real Gemini 3.5 Flash Lite Worker processes message and updates UI', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem(
      'blue.settings.v1',
      JSON.stringify({ mode: 'api', baseUrl: '', polling: false })
    );
  });

  // Execute worker once to process the pending message via real Gemini API
  console.log('Running background worker with real Gemini 3.5 Flash Lite...');
  const output = runDbHelper('process');
  console.log('Worker output:', output);
  expect(output).toContain('PROCESSED_COUNT:1');

  // Open the alert in browser
  await page.goto('/');
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(1);
  await expect(page.locator('.alerts-table')).toContainText('Высокий');

  const alertLink = page.locator('.alerts-table tbody tr a').first();
  await alertLink.click();

  // Alert detail should now display real risk score >= 75 and HIGH level
  await expect(page.locator('.score-display')).toHaveClass(/high/);
  await expect(page.locator('.score-number')).not.toContainText('—');

  // Verify exact evidence highlights and explanation
  const explanationDisclosure = page.locator('.explanation-disclosure');
  await explanationDisclosure.locator('summary').click();
  await expect(page.locator('.model-meta')).toContainText('gemini-3.5-flash-lite');

  // Review form should now be enabled
  await expect(page.locator('.review-form button')).toBeEnabled();
});

test('4. Live Analyst Review persists to PostgreSQL and updates UI', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem(
      'blue.settings.v1',
      JSON.stringify({ mode: 'api', baseUrl: '', polling: false })
    );
  });

  await page.goto('/');
  await page.locator('.alerts-table tbody tr a').first().click();

  // Select REVIEWED and type a note
  await page.getByLabel('Статус проверки').selectOption('REVIEWED');
  await page.getByLabel('Комментарий').fill('Подтверждено аналитиком: выявлены признаки пирамиды через browser E2E.');
  await page.getByRole('button', { name: 'Сохранить решение' }).click();

  // Toast / status notification
  await expect(page.getByRole('status')).toContainText('Решение сохранено на сервере.');

  // Reload page to verify persistence from PostgreSQL
  await page.reload();
  await expect(page.getByLabel('Статус проверки')).toHaveValue('REVIEWED');
  await expect(page.getByLabel('Комментарий')).toHaveValue('Подтверждено аналитиком: выявлены признаки пирамиды через browser E2E.');
});

test('5. Workspace Navigation & Settings connection check', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem(
      'blue.settings.v1',
      JSON.stringify({ mode: 'api', baseUrl: '', polling: false })
    );
  });

  // Navigate to Settings
  await page.goto('/settings');
  await page.getByRole('button', { name: 'Проверить подключение' }).click();
  await expect(page.locator('.service-connection')).toContainText('Подключение работает');

  // Navigate to Analytics
  await page.locator('.primary-nav').getByRole('link', { name: 'Аналитика' }).click();
  await expect(page.locator('.page-heading h1')).toContainText('Аналитика');

  // Navigate to Sources
  await page.locator('.primary-nav').getByRole('link', { name: 'Чаты и источники' }).click();
  await expect(page.locator('.page-heading h1')).toContainText('Источники');
  await expect(page.locator('.chat-card')).toContainText('Live Chat KZ');

  // Navigate back to Inbox
  await page.locator('.primary-nav').getByRole('link', { name: 'Входящие' }).click();
  await expect(page.locator('.inbox-title')).toContainText('1 сообщений');
});
