// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import ScholarBatchAdd from "./ScholarBatchAdd.vue";
import {
  parseScholarIds,
  parseScholarTokens,
  extractScholarIdFromUrl,
  validateTokenAsId,
} from "./scholar-batch-parsing";

const defaultProps = { saving: false, loading: false };

describe("parseScholarIds (unit)", () => {
  it("parses a single bare ID", () => {
    expect(parseScholarIds("A-UbBTPM15wL")).toEqual(["A-UbBTPM15wL"]);
  });

  it("parses multiple IDs separated by commas", () => {
    expect(parseScholarIds("A-UbBTPM15wL, B-UbBTPM15wL")).toEqual(["A-UbBTPM15wL", "B-UbBTPM15wL"]);
  });

  it("deduplicates IDs", () => {
    expect(parseScholarIds("A-UbBTPM15wL\nA-UbBTPM15wL")).toEqual(["A-UbBTPM15wL"]);
  });

  it("extracts ID from standard Google Scholar URL", () => {
    expect(parseScholarIds("https://scholar.google.com/citations?hl=en&user=A-UbBTPM15wL")).toEqual(["A-UbBTPM15wL"]);
  });

  it("extracts ID from URL with trailing slash", () => {
    expect(parseScholarIds("https://scholar.google.com/citations?user=A-UbBTPM15wL/")).toEqual(["A-UbBTPM15wL"]);
  });

  it("extracts ID from URL with fragment", () => {
    expect(parseScholarIds("https://scholar.google.com/citations?user=A-UbBTPM15wL#section")).toEqual(["A-UbBTPM15wL"]);
  });

  it("extracts ID from URL with extra query params", () => {
    expect(parseScholarIds("https://scholar.google.com/citations?hl=en&user=A-UbBTPM15wL&view_op=list_works&sortby=pubdate")).toEqual(["A-UbBTPM15wL"]);
  });

  it("handles URL-encoded characters in non-ID parts", () => {
    expect(parseScholarIds("https://scholar.google.com/citations?hl=en&user=A-UbBTPM15wL&label=%E4%B8%AD%E6%96%87")).toEqual(["A-UbBTPM15wL"]);
  });

  it("rejects malformed IDs (too short)", () => {
    expect(parseScholarIds("ABC123")).toEqual([]);
  });

  it("rejects malformed IDs (too long)", () => {
    expect(parseScholarIds("ABCDEF1234567")).toEqual([]);
  });

  it("rejects IDs with special characters", () => {
    expect(parseScholarIds("ABCDEF12345!")).toEqual([]);
  });

  it("rejects IDs with embedded whitespace", () => {
    expect(parseScholarIds("ABC DEF12345")).toEqual([]);
  });

  it("handles mixed valid and invalid tokens", () => {
    expect(parseScholarIds("A-UbBTPM15wL, invalid, B-UbBTPM15wL")).toEqual(["A-UbBTPM15wL", "B-UbBTPM15wL"]);
  });

  it("returns empty array for empty string", () => {
    expect(parseScholarIds("")).toEqual([]);
  });

  it("returns empty array for whitespace only", () => {
    expect(parseScholarIds("   ")).toEqual([]);
  });
});

describe("extractScholarIdFromUrl", () => {
  it("returns null for non-URL strings", () => {
    expect(extractScholarIdFromUrl("not-a-url")).toBeNull();
  });

  it("returns null for URL without user param", () => {
    expect(extractScholarIdFromUrl("https://scholar.google.com/citations?hl=en")).toBeNull();
  });

  it("extracts from URL with trailing slashes", () => {
    expect(extractScholarIdFromUrl("https://scholar.google.com/citations?user=A-UbBTPM15wL///")).toBe("A-UbBTPM15wL");
  });

  it("strips fragment before parsing", () => {
    expect(extractScholarIdFromUrl("https://scholar.google.com/citations?user=A-UbBTPM15wL#foo")).toBe("A-UbBTPM15wL");
  });

  it("returns null when user param is invalid length", () => {
    expect(extractScholarIdFromUrl("https://scholar.google.com/citations?user=short")).toBeNull();
  });
});

describe("validateTokenAsId", () => {
  it("returns null for valid 12-char ID", () => {
    expect(validateTokenAsId("ABCDEF123456")).toBeNull();
  });

  it("detects wrong length", () => {
    expect(validateTokenAsId("ABC")).toContain("12 characters");
  });

  it("detects invalid characters", () => {
    expect(validateTokenAsId("ABCDEF12345!")).toContain("invalid characters");
  });

  it("detects whitespace", () => {
    expect(validateTokenAsId("ABC DEF12345")).toContain("whitespace");
  });

  it("detects empty input", () => {
    expect(validateTokenAsId("")).toContain("empty");
  });
});

describe("parseScholarTokens (per-token errors)", () => {
  it("marks invalid tokens with error messages", () => {
    const tokens = parseScholarTokens("A-UbBTPM15wL, short, B-UbBTPM15wL");
    expect(tokens).toHaveLength(3);
    expect(tokens[0].id).toBe("A-UbBTPM15wL");
    expect(tokens[0].error).toBeNull();
    expect(tokens[1].id).toBeNull();
    expect(tokens[1].error).toContain("12 characters");
    expect(tokens[2].id).toBe("B-UbBTPM15wL");
  });

  it("marks duplicate tokens", () => {
    const tokens = parseScholarTokens("A-UbBTPM15wL, A-UbBTPM15wL");
    expect(tokens[1].error).toBe("duplicate");
  });

  it("marks bad URL tokens", () => {
    const tokens = parseScholarTokens("https://scholar.google.com/citations?hl=en");
    expect(tokens[0].error).toContain("could not extract");
  });
});

describe("ScholarBatchAdd (component)", () => {
  it("renders the heading and input", () => {
    const wrapper = mount(ScholarBatchAdd, { props: defaultProps });
    expect(wrapper.text()).toContain("Add Scholar Profiles");
    expect(wrapper.find("textarea").exists()).toBe(true);
  });

  it("shows parsed ID count as 0 for empty input", () => {
    const wrapper = mount(ScholarBatchAdd, { props: defaultProps });
    expect(wrapper.text()).toContain("Parsed IDs:");
  });

  it("parses bare scholar IDs from textarea input", async () => {
    const wrapper = mount(ScholarBatchAdd, { props: defaultProps });
    await wrapper.find("textarea").setValue("A-UbBTPM15wL");
    expect(wrapper.text()).toContain("1");
  });

  it("parses scholar IDs from Google Scholar URLs", async () => {
    const wrapper = mount(ScholarBatchAdd, { props: defaultProps });
    await wrapper.find("textarea").setValue(
      "https://scholar.google.com/citations?hl=en&user=A-UbBTPM15wL",
    );
    expect(wrapper.text()).toContain("1");
  });

  it("deduplicates IDs from mixed input", async () => {
    const wrapper = mount(ScholarBatchAdd, { props: defaultProps });
    await wrapper.find("textarea").setValue(
      "A-UbBTPM15wL\nhttps://scholar.google.com/citations?user=A-UbBTPM15wL",
    );
    expect(wrapper.text()).toContain("1");
  });

  it("parses multiple IDs separated by commas", async () => {
    const wrapper = mount(ScholarBatchAdd, { props: defaultProps });
    await wrapper.find("textarea").setValue("A-UbBTPM15wL, B-UbBTPM15wL");
    expect(wrapper.text()).toContain("2");
  });

  it("emits add-scholars with parsed IDs on submit", async () => {
    const wrapper = mount(ScholarBatchAdd, { props: defaultProps });
    await wrapper.find("textarea").setValue("A-UbBTPM15wL");
    await wrapper.find("form").trigger("submit");
    const emitted = wrapper.emitted("add-scholars");
    expect(emitted).toHaveLength(1);
    expect(emitted![0][0]).toEqual(["A-UbBTPM15wL"]);
  });

  it("clears textarea after successful submit", async () => {
    const wrapper = mount(ScholarBatchAdd, { props: defaultProps });
    const textarea = wrapper.find("textarea");
    await textarea.setValue("A-UbBTPM15wL");
    await wrapper.find("form").trigger("submit");
    expect((textarea.element as HTMLTextAreaElement).value).toBe("");
  });

  it("does not emit when input contains no valid IDs", async () => {
    const wrapper = mount(ScholarBatchAdd, { props: defaultProps });
    await wrapper.find("textarea").setValue("not-a-valid-id");
    await wrapper.find("form").trigger("submit");
    expect(wrapper.emitted("add-scholars")).toBeUndefined();
  });

  it("shows Adding... label when saving prop is true", () => {
    const wrapper = mount(ScholarBatchAdd, { props: { ...defaultProps, saving: true } });
    expect(wrapper.text()).toContain("Adding...");
  });

  it("shows validation errors for invalid tokens", async () => {
    const wrapper = mount(ScholarBatchAdd, { props: defaultProps });
    await wrapper.find("textarea").setValue("A-UbBTPM15wL, bad!");
    const errors = wrapper.find("[data-testid='validation-errors']");
    expect(errors.exists()).toBe(true);
  });

  it("shows skipped count alongside valid count", async () => {
    const wrapper = mount(ScholarBatchAdd, { props: defaultProps });
    await wrapper.find("textarea").setValue("A-UbBTPM15wL, tooshort");
    expect(wrapper.text()).toContain("1 valid");
    expect(wrapper.text()).toContain("1 skipped");
  });
});
