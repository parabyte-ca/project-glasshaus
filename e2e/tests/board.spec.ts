import { expect, test, type Page } from "@playwright/test";

import { api, makeProject } from "./helpers";

async function openBoard(page: Page, titles: string[]) {
  await page.goto("/");
  const project = await makeProject(page, "Board drag");
  const call = await api(page);
  for (const title of titles)
    await call("POST", "/api/v1/tasks", { project_id: project.id, title });
  await page.goto(`/projects/${project.key}?kind=board`);
  await expect(
    page.getByRole("button", { name: new RegExp(titles[0]!) }),
  ).toBeVisible();
  return { project, call };
}

async function statusOf(
  call: Awaited<ReturnType<typeof api>>,
  projectId: string,
  title: string,
) {
  const list = await call<{
    items: { title: string; status: { category: string } }[];
  }>("GET", `/api/v1/tasks?project_id=${projectId}`);
  return list.items.find((t) => t.title === title)?.status.category;
}

test("board: dragging a card with the mouse moves it, and a plain click still opens it", async ({
  page,
}) => {
  const { project, call } = await openBoard(page, ["Drag me", "Open me"]);
  const card = page.getByRole("button", { name: /Drag me/ });
  const done = page.getByRole("listitem", { name: /^Done, / });
  const from = (await card.boundingBox())!;
  const to = (await done.boundingBox())!;
  await page.mouse.move(from.x + 20, from.y + from.height / 2); // on the card's text, where a button sits
  await page.mouse.down();
  await page.mouse.move(from.x + 40, from.y + 30, { steps: 3 });
  await page.mouse.move(to.x + to.width / 2, to.y + 60, { steps: 12 });
  await page.mouse.up();
  await expect(done.getByText("Drag me")).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0); // the drop did not open the task
  await expect.poll(() => statusOf(call, project.id, "Drag me")).toBe("done");

  await page.getByRole("button", { name: /Open me/ }).click();
  await expect(page.getByRole("dialog").getByLabel("Title")).toHaveValue(
    "Open me",
  );
});

test.describe("on a touch screen", () => {
  test.use({ hasTouch: true });

  test("board: press and hold, then drag, moves a card; a quick swipe does not", async ({
    page,
  }) => {
    const { project, call } = await openBoard(page, ["Touch me"]);
    const card = page.getByRole("button", { name: /Touch me/ });
    const done = page.getByRole("listitem", { name: /^Done, / });
    const from = (await card.boundingBox())!;
    const to = (await done.boundingBox())!;
    const cdp = await page.context().newCDPSession(page);
    const touch = (
      type: "touchStart" | "touchMove" | "touchEnd",
      x: number,
      y: number,
    ) =>
      cdp.send("Input.dispatchTouchEvent", {
        type,
        touchPoints: type === "touchEnd" ? [] : [{ x, y }],
      });
    const sx = from.x + 20;
    const sy = from.y + from.height / 2;
    // A quick swipe is a scroll: nothing moves.
    await touch("touchStart", sx, sy);
    await touch("touchMove", sx + 60, sy + 5);
    await touch("touchEnd", 0, 0);
    expect(await statusOf(call, project.id, "Touch me")).toBe("todo");
    // Press and hold, then drag to Done.
    await touch("touchStart", sx, sy);
    await page.waitForTimeout(450);
    for (let i = 1; i <= 10; i++) {
      await touch(
        "touchMove",
        sx + ((to.x + to.width / 2 - sx) * i) / 10,
        sy + ((to.y + 60 - sy) * i) / 10,
      );
    }
    await touch("touchEnd", 0, 0);
    await expect(done.getByText("Touch me")).toBeVisible();
    await expect
      .poll(() => statusOf(call, project.id, "Touch me"))
      .toBe("done");
  });
});
