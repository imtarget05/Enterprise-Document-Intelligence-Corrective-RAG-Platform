import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

const MAX_LOCAL_PAGES = 100;
const MAX_LOCAL_CHARACTERS = 200_000;

/** Extract selectable PDF text for the isolated reviewer sandbox. Scanned
 * images still need the backend OCR pipeline. */
export async function extractPdfText(file: Blob, workerSrc = workerUrl): Promise<string> {
  const { getDocument, GlobalWorkerOptions } = await import("pdfjs-dist");
  GlobalWorkerOptions.workerSrc = workerSrc;

  const data = new Uint8Array(await file.arrayBuffer());
  const loadingTask = getDocument({ data, useSystemFonts: true });
  try {
    const pdf = await loadingTask.promise;
    if (pdf.numPages > MAX_LOCAL_PAGES) {
      throw new Error(`PDF có hơn ${MAX_LOCAL_PAGES} trang; cần backend để xử lý đầy đủ.`);
    }

    const pages: string[] = [];
    let characters = 0;
    for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber++) {
      const page = await pdf.getPage(pageNumber);
      const content = await page.getTextContent();
      const pageText = content.items
        .map((item) => ("str" in item ? `${item.str}${item.hasEOL ? "\n" : " "}` : ""))
        .join("")
        .trim();
      characters += pageText.length;
      if (characters > MAX_LOCAL_CHARACTERS) {
        throw new Error("PDF quá dài để xem trước trên trình duyệt; cần backend để xử lý đầy đủ.");
      }
      if (pageText) pages.push(pageText);
      page.cleanup();
    }
    const text = pages.join("\n\n").trim();
    if (text.length < 5) {
      throw new Error("PDF không có văn bản chọn được; cần backend OCR để đọc bản scan.");
    }
    return text;
  } finally {
    await loadingTask.destroy();
  }
}
