import { chromium, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import fs from "node:fs/promises";
import path from "node:path";
import os from "node:os";
if (process.env.LIVING_QA_APPROVAL === "1") {
  await import("./approval-regression.mjs");
  process.exit(process.exitCode || 0);
}
const out = path.resolve("test-results/living");
await fs.mkdir(out, { recursive: true });
const executablePath =
  process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ||
  path.join(
    os.homedir(),
    "Library/Caches/ms-playwright/chromium-1248/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
  );
const browser = await chromium.launch({ headless: true, executablePath });
const context = await browser.newContext({
  viewport: { width: 1440, height: 1050 },
  reducedMotion: "reduce",
});
const report = {
  kind: "Authored local browser QA; no provider calls, external accounts or human study",
  views: [],
  checks: [],
  errors: [],
};
context.on("page", (p) =>
  p.on("pageerror", (e) => report.errors.push(e.message)),
);
async function view(page, label, width) {
  await page.setViewportSize({ width, height: 1050 });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > innerWidth,
  );
  const axe = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  report.views.push({
    label,
    width,
    overflow,
    violations: axe.violations.map((v) => ({
      id: v.id,
      impact: v.impact,
      nodes: v.nodes.map((n) => ({
        target: n.target,
        summary: n.failureSummary,
      })),
    })),
  });
  await page.screenshot({
    path: path.join(out, `${label}-${width}.png`),
    fullPage: true,
  });
}

async function state(page) {
  return page.evaluate(async () => {
    const session = JSON.parse(
      localStorage.getItem("common-ground.living.session.v2") || "null",
    );
    const base = location.port === "4301" ? "http://127.0.0.1:4302" : "";
    const response = await fetch(base + "/api/v2/state", {
      headers: { Authorization: `Bearer ${session?.token}` },
      credentials: "omit",
    });
    if (!response.ok) throw new Error(`State unavailable ${response.status}`);
    return response.json();
  });
}
async function fullFlow(shared, context) {
  const original = await state(shared);
  const pickup = original.commitments.find((c) => c.task_id === "outbound");
  report.originalPickup = {
    event_id: pickup.event_id,
    etag: pickup.etag,
    agreement_id: original.agreement.agreement_id,
    revision: original.agreement.revision,
  };
  const people = {};
  for (const owner of original.owners) {
    const page = await context.newPage();
    people[owner.id] = page;
    await page.goto(owner.url);
    await page
      .getByRole("button", {
        name: "Enter this fictional owner space",
        exact: true,
      })
      .click();
    await expect(
      page.getByRole("heading", { name: "You choose what you can give." }),
    ).toBeVisible();
    if ((await state(page)).policy?.enabled) {
      await page
        .getByRole("button", {
          name: "Revoke carry-forward policy",
          exact: true,
        })
        .click();
      await expect
        .poll(async () => Boolean((await state(page)).policy.enabled))
        .toBe(false);
    }
    await view(page, `${owner.id}-decisions`, owner.id === "asha" ? 1440 : 390);
  }
  report.checks.push(
    "All three owner carry-forward policies are off; any prior authored policy was explicitly revoked through its owner UI",
  );
  await shared
    .getByRole("button", { name: "New shared goal", exact: true })
    .click();
  await shared
    .getByRole("textbox", { name: "The shared request", exact: true })
    .fill(
      "A fictional goal needs its explicit dates, durations, windows, subject and routes reviewed before confirmation.",
    );
  await shared
    .getByRole("button", { name: "Open structured review", exact: true })
    .click();
  await expect(shared.locator(".cg-task-editor")).toHaveCount(2);
  for (const input of await shared
    .locator(
      '.cg-task-editor input[type="date"], .cg-task-editor input[type="number"], .cg-task-editor input[type="time"]',
    )
    .all())
    await expect(input).toHaveValue("");
  await expect(
    shared.getByRole("button", { name: "Confirm reviewed goal", exact: true }),
  ).toBeDisabled();
  await view(shared, "missing-facts-review", 1440);
  await view(shared, "missing-facts-review", 320);
  await shared
    .getByRole("button", { name: "Close new goal", exact: true })
    .click();
  report.checks.push(
    "Local structured review exposes complete editable graph and routes; missing dates, durations and time windows remain blank; confirmation requires explicit review",
  );
  const ravi = people.ravi;
  await ravi
    .locator(".cg-withdraw-list li")
    .filter({ hasText: "Bring Dev home" })
    .getByRole("checkbox")
    .check();
  await ravi
    .getByRole("button", { name: "Review selected withdrawal", exact: true })
    .click();
  await ravi
    .getByRole("button", { name: "Withdraw selected parts", exact: true })
    .click();
  await expect
    .poll(async () => (await state(shared)).status)
    .toBe("NEEDS_HELP");
  await shared.reload();
  await expect(
    shared.getByRole("heading", {
      name: "A required part is still uncovered.",
    }),
  ).toBeVisible();
  for (const width of [1440, 320]) await view(shared, "uncovered", width);
  await shared
    .getByRole("button", { name: "Find a structured arrangement", exact: true })
    .click();
  await expect
    .poll(async () =>
      (await state(shared)).questions.some(
        (q) => q.owner_id === "leena" && q.task_id === "return",
      ),
    )
    .toBe(true);
  const leena = people.leena;
  await leena.reload();
  await leena
    .getByRole("button", { name: "Preview exact public offer", exact: true })
    .click();
  await expect(leena.locator(".cg-release-preview")).toContainText("16:15");
  await view(leena, "conditional-release", 390);
  await leena
    .getByRole("checkbox", { name: /I reviewed the tasks, windows/ })
    .check();
  await leena
    .getByRole("button", { name: "Release this exact offer", exact: true })
    .click();
  await expect(leena.locator(".cg-release-preview")).toHaveCount(0);
  await shared
    .getByRole("button", { name: "Find a structured arrangement", exact: true })
    .click();
  await expect
    .poll(async () => Boolean((await state(shared)).pending))
    .toBe(true);
  await shared.reload();
  await view(shared, "amendment", 1440);
  await view(shared, "amendment", 320);
  const proposal = await state(shared);
  expect(
    proposal.pending.delta.calendar_mutations.map((m) => m.kind).sort(),
  ).toEqual(["delete", "insert"]);
  for (const id of ["leena", "asha", "ravi"]) {
    const page = people[id];
    await page.reload();
    await expect(
      page.getByRole("heading", { name: "Your part in the next arrangement." }),
    ).toBeVisible();
    await page
      .getByRole("checkbox", { name: /I reviewed this exact revision/ })
      .check();
    await page
      .getByRole("button", { name: "Approve my exact part", exact: true })
      .click();
  }
  await expect.poll(async () => (await state(shared)).status).toBe("READY");
  await shared.reload();
  await shared
    .getByRole("button", { name: "Apply approved changes", exact: true })
    .click();
  await expect.poll(async () => (await state(shared)).status).toBe("ACTIVE");
  await shared.reload();
  const repaired = await state(shared),
    retained = repaired.commitments.find((c) => c.task_id === "outbound");
  report.retainedPickup = {
    event_id: retained.event_id,
    etag: retained.etag,
    agreement_id: repaired.agreement.agreement_id,
    revision: repaired.agreement.revision,
  };
  expect([retained.event_id, retained.etag]).toEqual([
    pickup.event_id,
    pickup.etag,
  ]);
  expect(
    repaired.commitments.find((c) => c.task_id === "return").owner_id,
  ).toBe("leena");
  for (const width of [1440, 390, 320]) await view(shared, "repaired", width);
  report.checks.push(
    "Actual local authored flow: Ravi withdrew only return; Leena released the Asha-by-16:15 condition; owners gave exact review; persisted amendment requested one insert and one delete; pickup event ID and ETag unchanged",
  );
  const asha = people.asha;
  await asha
    .getByRole("button", { name: "Private memory", exact: true })
    .click();
  await view(asha, "memory", 320);
  await asha
    .getByRole("button", { name: "Add a reviewed rule", exact: true })
    .click();
  await asha
    .getByRole("textbox", { name: /Private note · never shared/ })
    .fill("UI_QA_PRIVATE_NOTE_ONLY");
  await asha
    .getByRole("checkbox", { name: /I reviewed this structured rule/ })
    .check();
  await asha
    .getByRole("button", { name: "Save reviewed memory", exact: true })
    .click();
  await expect(asha.locator(".cg-memory-editor")).toHaveCount(0);
  const card = asha
    .locator(".cg-memory")
    .filter({ hasText: "Owner reviewed directly" });
  await card.getByRole("button", { name: "Correct rule", exact: true }).click();
  await asha
    .getByRole("textbox", { name: "Provenance", exact: true })
    .fill("Authored UI QA correction");
  await asha
    .getByRole("checkbox", { name: /I reviewed this structured rule/ })
    .check();
  await asha
    .getByRole("button", { name: "Save reviewed memory", exact: true })
    .click();
  const corrected = asha
    .locator(".cg-memory")
    .filter({ hasText: "Authored UI QA correction" });
  await expect(corrected).toBeVisible();
  await corrected
    .getByRole("button", { name: "Delete memory", exact: true })
    .click();
  await corrected
    .getByRole("button", { name: "Delete this memory", exact: true })
    .click();
  await expect(corrected).toHaveCount(0);
  const evidence = await shared.evaluate(async () => {
    const s = JSON.parse(
      localStorage.getItem("common-ground.living.session.v2"),
    );
    return (
      await fetch("http://127.0.0.1:4302/api/v2/evidence", {
        headers: { Authorization: `Bearer ${s.token}` },
      })
    ).text();
  });
  expect(evidence).not.toContain("UI_QA_PRIVATE_NOTE_ONLY");
  report.checks.push(
    "Owner-local memory created, corrected and deleted through UI; authored private note absent from broker evidence",
  );
  await leena.getByRole("button", { name: "My calendar", exact: true }).click();
  await view(leena, "calendar", 390);
  let failures = 0;
  await shared.route("**/api/v2/state", (route) => {
    failures++;
    return route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({
        detail: "Authored browser QA session-expiry response",
      }),
    });
  });
  await expect(
    shared.getByRole("button", {
      name: "Re-enter fictional shared room",
      exact: true,
    }),
  ).toBeVisible({ timeout: 10000 });
  const stopped = failures;
  await shared.waitForTimeout(4500);
  expect(failures).toBe(stopped);
  await expect(shared.locator(".cg-timeline")).toBeVisible();
  await view(shared, "historical-expired", 390);
  await shared.unroute("**/api/v2/state");
  report.checks.push(
    "Injected browser session-expiry response retains historical timeline and stops unauthenticated polling",
  );
}

try {
  const p = await context.newPage();
  await p.goto("http://127.0.0.1:4301");
  await expect(
    p.getByRole("button", {
      name: "Try the fictional care circle",
      exact: true,
    }),
  ).toBeVisible();
  for (const width of [1440, 1024, 768, 390, 320])
    await view(p, "entry", width);
  report.checks.push(
    "Public entry exposes fictional circle and recorded legacy access without owner credentials",
  );
  const recorded = await context.newPage();
  await recorded.goto("http://127.0.0.1:4301/?recorded=1");
  await expect(
    recorded.getByRole("heading", { name: "What was actually observed." }),
  ).toBeVisible();
  for (const width of [1440, 390, 320]) await view(recorded, "recorded", width);
  const ownerEntry = await context.newPage();
  await ownerEntry.goto("http://127.0.0.1:4311");
  for (const width of [1440, 390, 320])
    await view(ownerEntry, "owner-entry", width);
  report.checks.push(
    "Original recorded evidence is readable with no session; separate owner entry is responsive",
  );
  if (process.env.LIVING_QA_REUSE === "1") {
    await p.evaluate(async () => {
      const r = await fetch("http://127.0.0.1:4302/sample/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
        credentials: "omit",
      });
      if (!r.ok) throw new Error("Sample reentry failed");
      localStorage.setItem(
        "common-ground.living.session.v2",
        JSON.stringify(await r.json()),
      );
    });
    await p.reload();
    await expect(
      p.getByRole("heading", { name: "Who’s doing what" }),
    ).toBeVisible();
    report.checks.push(
      "Re-entered existing fictional arrangement without creating a new sample",
    );
  }
  if (
    process.env.LIVING_QA_SAMPLE === "1" &&
    process.env.LIVING_QA_REUSE !== "1"
  ) {
    await p.setViewportSize({ width: 1440, height: 1050 });
    await p
      .getByRole("button", {
        name: "Try the fictional care circle",
        exact: true,
      })
      .click();
    await expect(
      p.getByRole("heading", { name: "Who’s doing what" }),
    ).toBeVisible({ timeout: 30000 });
    for (const width of [1440, 390, 320]) await view(p, "arrangement", width);
    await p
      .getByRole("button", { name: "New shared goal", exact: true })
      .click();
    for (const width of [1440, 320]) await view(p, "goal", width);
    await p.getByRole("button", { name: "Close new goal" }).click();
    await p.getByRole("button", { name: "The record", exact: true }).click();
    await view(p, "record", 390);
    report.checks.push(
      "Real fictional session and sample API populate arrangement; graph form and portable record reachable",
    );
  }
  if (process.env.LIVING_QA_FULL === "1") {
    await p
      .getByRole("button", { name: "Our arrangement", exact: true })
      .click();
    await fullFlow(p, context);
  }
} catch (error) {
  report.errors.push(error.message);
} finally {
  await fs.writeFile(
    path.join(out, "report.json"),
    JSON.stringify(report, null, 2),
  );
  await browser.close();
}
console.log(JSON.stringify(report, null, 2));
if (
  report.errors.length ||
  report.views.some((v) => v.overflow || v.violations.length)
)
  process.exitCode = 1;
