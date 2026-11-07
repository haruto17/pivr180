import { render } from "svelte/server";
import { describe, expect, it } from "vitest";
import Page from "./+page.svelte";

describe("+page.svelte", () => {
  it("renders the app title", () => {
    const { body } = render(Page);
    expect(body).toContain("pivr180 editor");
  });
});
