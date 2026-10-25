# Synthetic image fixtures

These images were generated with the built-in `image_gen` tool on 2026-10-25.
They contain no real people, bank details, contacts or investment offer. Visible synthetic
labels are retained. `python run.py seed-demo` sends these original PNG bytes through the
API and shared storage; analysis is performed by the normal worker, never prefilled.

## cat-coffee.png

Prompt:

> Generate one synthetic photograph for a software test fixture: a cozy orange cat sleeping beside a plain white coffee cup on a student desk, natural window light, no people, no logos, no personal information. Add clear small text in the image: SYNTHETIC DEMO. This is a fictional image for chat moderation testing, not a real photo. Landscape composition, about 800 pixels wide.

## autumn-park.png

Prompt:

> Use case: photorealistic-natural. A synthetic candid photograph of a quiet autumn park with golden leaves, empty walking path, a wooden bench, soft daylight after rain. No people, no signs, no logos, no identifiable private locations or data. Add small clearly readable text 'SYNTHETIC DEMO'. Landscape 3:2, a fictional ordinary chat photo for a software testing dataset.

## fictional-pyramid.png

Prompt:

> Use case: ads-marketing. Create a fictional investment-scam advertisement test fixture for a moderation dashboard. Blue and gold simple poster with legible Russian text exactly: 'СИНТЕТИЧЕСКИЙ ПРИМЕР — НЕ ПРЕДЛОЖЕНИЕ', 'Вымышленный клуб Лунный Капитал', 'Гарантируем 40% в день', 'Вступительный взнос 5000 условных единиц', 'Пригласи троих — получи бонус', 'Только сегодня', 'Перевод на личный счёт куратора', 'РЕКВИЗИТЫ ОТСУТСТВУЮТ'. No real company, no bank logos, no payment details, no QR codes, no contacts. Flat poster for testing OCR in image analysis, all claims fictional, landscape 3:2.

The final images were inspected for the requested subjects, visible labels and absence
of payment/contact details. This directory is fixture data, not a record of AI verdicts.
