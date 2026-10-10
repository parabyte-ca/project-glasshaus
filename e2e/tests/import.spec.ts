import { deflateRawSync } from 'node:zlib';

import { expect, test } from '@playwright/test';

import { api, expectAccessible, makeProject } from './helpers';

// A minimal .xlsx (a zip of a few XML parts) with text cells, so the real Excel reader runs in the browser.
function crc32(buf: Buffer): number {
  let crc = ~0;
  for (const byte of buf) {
    crc ^= byte;
    for (let k = 0; k < 8; k++) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
  }
  return ~crc >>> 0;
}

function zip(files: Record<string, string>): Buffer {
  const parts: Buffer[] = [];
  const central: Buffer[] = [];
  let offset = 0;
  for (const [name, text] of Object.entries(files)) {
    const data = Buffer.from(text);
    const packed = deflateRawSync(data);
    const nameBuf = Buffer.from(name);
    const head = Buffer.alloc(30);
    head.writeUInt32LE(0x04034b50, 0);
    head.writeUInt16LE(20, 4);
    head.writeUInt16LE(8, 8);
    head.writeUInt32LE(crc32(data), 14);
    head.writeUInt32LE(packed.length, 18);
    head.writeUInt32LE(data.length, 22);
    head.writeUInt16LE(nameBuf.length, 26);
    const dir = Buffer.alloc(46);
    dir.writeUInt32LE(0x02014b50, 0);
    dir.writeUInt16LE(20, 4);
    dir.writeUInt16LE(20, 6);
    dir.writeUInt16LE(8, 10);
    dir.writeUInt32LE(crc32(data), 16);
    dir.writeUInt32LE(packed.length, 20);
    dir.writeUInt32LE(data.length, 24);
    dir.writeUInt16LE(nameBuf.length, 28);
    dir.writeUInt32LE(offset, 42);
    parts.push(head, nameBuf, packed);
    central.push(dir, nameBuf);
    offset += head.length + nameBuf.length + packed.length;
  }
  const size = central.reduce((n, b) => n + b.length, 0);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(Object.keys(files).length, 8);
  end.writeUInt16LE(Object.keys(files).length, 10);
  end.writeUInt32LE(size, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...parts, ...central, end]);
}

function xlsx(rows: string[][]): Buffer {
  const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const col = (i: number) => String.fromCharCode(65 + i);
  const sheet = rows
    .map(
      (r, y) =>
        `<row r="${y + 1}">${r
          .map((v, x) => `<c r="${col(x)}${y + 1}" t="inlineStr"><is><t>${esc(v)}</t></is></c>`)
          .join('')}</row>`,
    )
    .join('');
  const ns = 'http://schemas.openxmlformats.org';
  return zip({
    '[Content_Types].xml': `<?xml version="1.0" encoding="UTF-8"?><Types xmlns="${ns}/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>`,
    '_rels/.rels': `<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="${ns}/package/2006/relationships"><Relationship Id="rId1" Type="${ns}/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>`,
    'xl/workbook.xml': `<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="${ns}/spreadsheetml/2006/main" xmlns:r="${ns}/officeDocument/2006/relationships"><sheets><sheet name="Work items" sheetId="1" r:id="rId1"/></sheets></workbook>`,
    'xl/_rels/workbook.xml.rels': `<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="${ns}/package/2006/relationships"><Relationship Id="rId1" Type="${ns}/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>`,
    'xl/worksheets/sheet1.xml': `<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="${ns}/spreadsheetml/2006/main"><sheetData>${sheet}</sheetData></worksheet>`,
  });
}

test('import tasks from CSV, then update them from an Excel file', async ({ page }) => {
  await page.goto('/');
  const project = await makeProject(page, 'Imported work');
  const me = await (await api(page))<{ email: string }>('GET', '/api/v1/users/me');

  await page.goto(`/projects/${project.key}`);
  await page.getByRole('link', { name: 'Import', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Import tasks', level: 1 })).toBeVisible();
  await page.getByLabel('Exported from').selectOption('nimble');
  const csv = [
    'Work Item ID,Title,Lane,Owner,Due Date,Comments',
    `N-1,Plan the launch,In Progress,${me.email},2026-10-15,Kick-off notes`,
    'N-2,Write the FAQ,Done,someone@nowhere.example,2026-10-20,',
  ].join('\n');
  await page.getByLabel('File').setInputFiles({ name: 'nimble.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) });
  await expect(page.getByRole('heading', { name: /Columns \(2 rows\)/ })).toBeVisible();
  await expect(page.getByLabel('Import Comments as')).toHaveValue('comments');
  await expectAccessible(page, 'import page');

  await page.getByRole('button', { name: 'Check' }).click();
  await expect(page.getByText(/2 new, 0 updated and 0 unchanged tasks would be imported/)).toBeVisible();
  await expect(page.getByText(/someone@nowhere.example: not found in Glasshaus/)).toBeVisible();
  await page.getByRole('button', { name: 'Import 2 rows' }).click();
  await expect(page.getByText(/2 new, 0 updated and 0 unchanged tasks were imported, with 1 comment\./)).toBeVisible();

  await page.getByRole('link', { name: 'Open Imported work' }).click();
  await expect(page.getByText('Plan the launch')).toBeVisible();
  await page.getByLabel('Show completed').check(); // "Done" in the file became the Done status
  await expect(page.getByText('Write the FAQ')).toBeVisible();

  // The same items from Excel: matched by ID, so the renamed one updates instead of being added.
  await page.goto(`/projects/${project.key}/import`);
  await page.getByLabel('Exported from').selectOption('nimble');
  await page.getByLabel('File').setInputFiles({
    name: 'nimble.xlsx',
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    buffer: xlsx([
      ['Work Item ID', 'Title', 'Lane'],
      ['N-1', 'Plan the launch event', 'In Progress'],
      ['N-2', 'Write the FAQ', 'Done'],
    ]),
  });
  await expect(page.getByRole('heading', { name: /Columns \(2 rows\)/ })).toBeVisible();
  await page.getByRole('button', { name: 'Import 2 rows' }).click();
  await expect(page.getByText(/0 new, 1 updated and 1 unchanged tasks were imported/)).toBeVisible();
  const tasks = await (await api(page))<{ items: { title: string }[] }>(
    'GET',
    `/api/v1/tasks?project_id=${project.id}`,
  );
  expect(tasks.items.map((t) => t.title).sort()).toEqual(['Plan the launch event', 'Write the FAQ']);
});
