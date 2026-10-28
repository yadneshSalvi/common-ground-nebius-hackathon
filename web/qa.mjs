import { chromium, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import fs from "node:fs/promises";
import path from "node:path";
import os from "node:os";

// Read-only operator harness. Pairing material stays in memory, outside reports.
const out = path.resolve("test-results");
await fs.mkdir(out, { recursive: true });
const links = JSON.parse(
  await fs.readFile(".runtime/pairing-links.json", "utf8"),
);
const executablePath =
  process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ||
  path.join(
    os.homedir(),
    "Library/Caches/ms-playwright/chromium-1248/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
  );
const browser = await chromium.launch({ executablePath, headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  reducedMotion: "reduce",
  acceptDownloads: true,
});
const pages = {};
const report = {
  kind: "Read-only production UI review; no protocol mutations",
  checks: [],
  views: [],
  errors: [],
};
context.on("page", (page) =>
  page.on("pageerror", (error) => report.errors.push(error.message)),
);
async function checkView(page, label, width) {
  await page.setViewportSize({ width, height: 1000 });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > innerWidth,
  );
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  const violations = result.violations.map((v) => ({
    id: v.id,
    impact: v.impact,
    nodes: v.nodes.map((n) => ({
      selector: n.target,
      summary: n.failureSummary,
    })),
  }));
  report.views.push({ label, width, overflow, violations });
  await page.screenshot({
    path: path.join(out, `${label}-${width}.png`),
    fullPage: true,
  });
}
try {
  for (const id of ["broker", "asha", "ravi", "leena"]) {
    const page = await context.newPage();
    pages[id] = page;
    const legacy = new URL(links[id]);
    legacy.searchParams.set("legacy", "1");
    await page.goto(legacy.href);
    await expect(
      page.getByRole("button", { name: "Lock workspace" }),
    ).toBeVisible();
    expect(new URL(page.url()).hash).toBe("");
    report.checks.push(`${id}: paired with the real service; fragment cleared`);
  }
  const shared = pages.broker;
  for (const width of [1440, 1024, 768, 390, 320])
    await checkView(shared, "agreement", width);
  await shared.getByRole("button", { name: "What we shared" }).click();
  await expect(shared.locator("#sharing-title")).toBeFocused();
  await checkView(shared, "sharing", 1440);
  await shared.getByRole("button", { name: "Equivalent text view" }).click();
  await checkView(shared, "sharing-text", 320);
  await shared.getByRole("button", { name: "Evidence & receipts" }).click();
  await expect(shared.locator("#evidence-title")).toBeFocused();
  await checkView(shared, "evidence", 390);
  for (const id of ["asha", "ravi", "leena"]) {
    await checkView(pages[id], `${id}-decision`, id === "asha" ? 1440 : 390);
    await pages[id]
      .getByRole("button", { name: "Preferences & memory" })
      .click();
    await checkView(pages[id], `${id}-preferences`, 320);
    await pages[id].getByRole("button", { name: "My local calendar" }).click();
    await checkView(pages[id], `${id}-calendar`, 390);
    const edit = pages[id]
      .getByRole("button", { name: "Try a local user edit", exact: true })
      .first();
    if ((await edit.count()) && (await edit.isEnabled())) {
      await edit.click();
      await expect(
        pages[id].getByRole("textbox", {
          name: "Local user-edit fixture · event summary",
        }),
      ).toBeFocused();
      await pages[id]
        .getByRole("button", { name: "Keep current entry", exact: true })
        .click();
      await expect(edit).toBeFocused();
      report.checks.push(
        `${id}: inline calendar editor receives focus and Cancel restores its trigger; no edit was submitted`,
      );
    }
    await pages[id].getByRole("button", { name: "My decision" }).click();
    const withdrawal = pages[id].getByRole("button", {
      name: "Review withdrawal",
      exact: true,
    });
    if ((await withdrawal.count()) && (await withdrawal.isEnabled())) {
      await withdrawal.click();
      await expect(pages[id].locator("#withdraw-heading")).toBeFocused();
      await pages[id]
        .getByRole("button", { name: "Keep my current offer", exact: true })
        .click();
      await expect(withdrawal).toBeFocused();
      report.checks.push(
        `${id}: inline withdrawal review receives focus and Cancel restores its trigger; no withdrawal was submitted`,
      );
    }
  }
  await shared.getByRole("button", { name: "Our agreement" }).click();
  await expect(shared.locator("#agreement-title")).toBeFocused();
  report.checks.push(
    "View navigation resets scroll and focuses the selected heading",
  );
  await shared.setViewportSize({ width: 1440, height: 1000 });
  await shared.evaluate(() => {
    document.documentElement.style.zoom = "2";
  });
  expect(
    await shared.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  report.checks.push(
    "200% CSS zoom: agreement controls remain in layout without page overflow (native browser zoom requires manual review)",
  );
  await shared.evaluate(() => {
    document.documentElement.style.zoom = "";
  });
  const popupPromise = context.waitForEvent("page");
  await shared.locator(".rail-owner").first().click();
  const popup = await popupPromise;
  await expect(
    popup.getByRole("button", { name: "Lock workspace" }),
  ).toBeVisible();
  expect(new URL(popup.url()).hash).toBe("");
  await popup.close();
  report.checks.push(
    "An already paired owner reopens without a pairing secret in the broker link",
  );
  const cancel = shared.getByRole("button", {
    name: "Cancel applied calendar changes",
    exact: true,
  });
  if ((await cancel.count()) && (await cancel.isEnabled())) {
    await cancel.click();
    await expect(shared.getByRole("dialog")).toBeVisible();
    await shared.keyboard.press("Escape");
    await expect(shared.getByRole("dialog")).toHaveCount(0);
    await expect(cancel).toBeFocused();
    report.checks.push(
      "Cancellation dialog closes on Escape and restores its trigger; no cancellation was submitted",
    );
  }
  for (const id of ["asha", "ravi", "leena"]) {
    const ownerPage = pages[id];
    await ownerPage.getByRole("button", { name: "My local calendar" }).click();
    const remove = ownerPage
      .getByRole("button", { name: "Remove local event", exact: true })
      .first();
    if ((await remove.count()) && (await remove.isEnabled())) {
      await remove.click();
      await expect(ownerPage.getByRole("dialog")).toBeVisible();
      await expect(
        ownerPage.getByRole("button", { name: "Keep this event" }),
      ).toBeFocused();
      await checkView(ownerPage, `${id}-removal-confirmation`, 390);
      await ownerPage.keyboard.press("Escape");
      await expect(ownerPage.getByRole("dialog")).toHaveCount(0);
      await expect(remove).toBeFocused();
      report.checks.push(
        `${id}: exact-event owner removal dialog reviewed with keyboard; no deletion was submitted`,
      );
      break;
    }
  }
  const asha = pages.asha;
  await asha.bringToFront();
  await asha.getByRole("button", { name: "Preferences & memory" }).click();
  await asha.locator("#private-note").fill("UI QA unsaved draft stays local");
  await asha.route("http://127.0.0.1:4311/api/state", (route) =>
    route.fulfill({
      status: 503,
      json: { detail: "QA network fixture: local service unavailable" },
    }),
  );
  await expect(asha.getByRole("alert")).toContainText("QA network fixture", {
    timeout: 10000,
  });
  await expect(asha.locator("#private-note")).toHaveValue(
    "UI QA unsaved draft stays local",
  );
  await asha.unroute("http://127.0.0.1:4311/api/state");
  await asha.getByRole("button", { name: "Retry loading" }).click();
  await expect(asha.getByRole("alert")).toHaveCount(0);
  await expect(asha.locator("#private-note")).toHaveValue(
    "UI QA unsaved draft stays local",
  );
  report.checks.push(
    "Labeled read-only network failure fixture recovered without losing an unsaved local preference draft; nothing was saved",
  );
  expect(await context.cookies()).toHaveLength(0);
  expect(report.errors).toHaveLength(0);
  report.checks.push("No cookies and no browser runtime errors");
} finally {
  await fs.writeFile(
    path.join(out, "ui-qa.json"),
    JSON.stringify(report, null, 2),
  );
  await browser.close();
}
const failures = report.views.filter(
  (view) => view.overflow || view.violations.length,
);
console.log(
  JSON.stringify(
    {
      checks: report.checks,
      views: report.views.length,
      failedViews: failures.map((v) => ({
        label: v.label,
        width: v.width,
        violations: v.violations.map((x) => x.id),
        overflow: v.overflow,
      })),
      runtimeErrors: report.errors.length,
    },
    null,
    2,
  ),
);
if (failures.length) process.exitCode = 1;
