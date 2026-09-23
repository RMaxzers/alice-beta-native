import { marked } from "marked";
import DOMPurify from "dompurify";

// Model output and document text are untrusted: parse Markdown, then sanitize. No raw HTML survives
// beyond a formatting allowlist, and links always open in a new tab without referrer/opener.
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A") {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  }
});

const ALLOWED_TAGS = ["p", "br", "strong", "em", "del", "code", "pre", "blockquote", "ul", "ol", "li",
  "h1", "h2", "h3", "h4", "h5", "h6", "a", "table", "thead", "tbody", "tr", "th", "td", "hr"];

export function renderMarkdown(src: string): string {
  const html = marked.parse(src, { async: false, gfm: true, breaks: true }) as string;
  return DOMPurify.sanitize(html, { ALLOWED_TAGS, ALLOWED_ATTR: ["href", "title"], ALLOWED_URI_REGEXP: /^(https?:|\/api\/documents\/|#)/i });
}
