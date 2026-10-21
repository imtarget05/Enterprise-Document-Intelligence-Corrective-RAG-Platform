interface WelcomeScreenProps {
  onUploadClick: () => void;
  onSelectPrompt?: (text: string) => void;
  hasDocuments?: boolean;
}

const SUGGESTED_PROMPTS = [
  { icon: "📄", text: "Tóm tắt tài liệu này" },
  { icon: "⚖️", text: "Điều khoản pháp lý quan trọng" },
  { icon: "🔍", text: "So sánh các điều khoản" },
  { icon: "📋", text: "Trích xuất các điểm chính" },
];

export default function WelcomeScreen({ onUploadClick, onSelectPrompt, hasDocuments = false }: WelcomeScreenProps) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-6 py-12 animate-fade-in">
      {/* Logo + heading */}
      <div className="flex flex-col items-center mb-10">
        <div className="w-16 h-16 bg-google-blue rounded-material-2xl flex items-center justify-center mb-5 shadow-material-2">
          <svg width="32" height="32" viewBox="0 0 24 24">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" fill="white" opacity="0.3" />
            <polyline points="14 2 14 8 20 8" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" />
            <line x1="16" y1="13" x2="8" y2="13" stroke="white" strokeWidth="2" strokeLinecap="round" />
            <line x1="16" y1="17" x2="8" y2="17" stroke="white" strokeWidth="2" strokeLinecap="round" />
          </svg>
        </div>
        <h2 className="text-[28px] text-onsurface font-normal tracking-tight mb-2">
          Chào mừng đến với Smart Document
        </h2>
        <p className="text-[15px] text-onsurface-muted max-w-md text-center leading-6">
          Nền tảng AI giúp bạn tra cứu, phân tích và đặt câu hỏi về tài liệu pháp lý một cách nhanh chóng, chính xác.
        </p>
      </div>

      {/* Suggested prompts */}
      <div className="w-full max-w-lg space-y-3">
        <p className="text-[13px] text-onsurface-muted text-center font-medium mb-4">Gợi ý bắt đầu</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {SUGGESTED_PROMPTS.map((prompt, i) => (
            <button
              key={i}
              onClick={() => onSelectPrompt ? onSelectPrompt(prompt.text) : onUploadClick()}
              className="flex items-center gap-3 px-4 py-3.5 rounded-material-lg border border-outline hover:bg-surface-container hover:shadow-material-btn transition-all duration-200 text-left group"
            >
              <span className="text-[20px]">{prompt.icon}</span>
              <span className="text-[13px] text-onsurface-variant group-hover:text-onsurface transition-colors duration-200">
                {prompt.text}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Upload CTA */}
      <div className="mt-10">
        <button
          onClick={onUploadClick}
          className="flex items-center gap-2.5 px-6 py-3 bg-google-blue hover:bg-google-blueDark text-white rounded-material-full text-[14px] font-medium shadow-material-btn hover:shadow-material-btn-hover transition-all duration-200"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
          {hasDocuments ? "Tải lên tài liệu mới" : "Tải lên tài liệu đầu tiên"}
        </button>
      </div>
    </div>
  );
}
