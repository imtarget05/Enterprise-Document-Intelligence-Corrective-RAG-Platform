import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { describe, expect, it } from "vitest";
import { extractPdfText } from "./extractPdfText";

function makePdf(text: string): Blob {
  const escaped = text.replaceAll("\\", "\\\\").replaceAll("(", "\\(").replaceAll(")", "\\)");
  const stream = `BT /F1 12 Tf 72 720 Td (${escaped}) Tj ET`;
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  for (const [index, object] of objects.entries()) {
    offsets.push(pdf.length);
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
  }
  const xrefOffset = pdf.length;
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (const offset of offsets.slice(1)) pdf += `${String(offset).padStart(10, "0")} 00000 n \n`;
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF`;
  return {
    arrayBuffer: async () => new TextEncoder().encode(pdf).buffer,
  } as Blob;
}

describe("selectable PDF extraction", () => {
  const workerSrc = pathToFileURL(resolve(process.cwd(), "node_modules/pdfjs-dist/build/pdf.worker.min.mjs")).href;

  it("reads the actual text of a PDF page", async () => {
    await expect(extractPdfText(makePdf("Ticket price is 450000 VND"), workerSrc)).resolves.toContain("450000 VND");
  });

  it("rejects a PDF without selectable text", async () => {
    await expect(extractPdfText(makePdf(""), workerSrc)).rejects.toThrow(/không có văn bản/);
  });
});
