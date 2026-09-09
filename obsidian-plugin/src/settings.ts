export type OcrEngine = 'tesseract' | 'azure_ocr' | 'azure_document_intelligence' | 'win_ocr';

export interface PluginSettings {
    // method toggles
    useMarkitdown: boolean;
    useOcr: boolean;
    useAi: boolean;
    // priority order of the three blocks
    blockPriority: string[];
    // OCR sub-engine priority
    ocrPriority: OcrEngine[];
    // AI extras
    aiAutoDetect: boolean;
    aiImprove: boolean;
    // credentials & model
    geminiApiKey: string;
    azureOcrKey: string;
    azureOcrEndpoint: string;
    azureDocumentIntelligenceKey: string;
    azureDocumentIntelligenceEndpoint: string;
    tesseractLang: string;
    tesseractCmd: string;
    modelName: string;
    promptOverride: string;
    // misc
    footerTemplate: string;
    useSeparatePluginSettings: boolean;
}

export const DEFAULT_SETTINGS: PluginSettings = {
    useMarkitdown: true,
    useOcr: false,
    useAi: false,
    blockPriority: ['markitdown', 'ocr', 'ai'],
    ocrPriority: ['azure_document_intelligence', 'tesseract', 'azure_ocr', 'win_ocr'],
    aiAutoDetect: false,
    aiImprove: false,
    geminiApiKey: '',
    azureOcrKey: '',
    azureOcrEndpoint: '',
    azureDocumentIntelligenceKey: '',
    azureDocumentIntelligenceEndpoint: '',
    tesseractLang: 'deu+eng',
    tesseractCmd: '',
    modelName: 'gemini-3.1-flash-lite',
    promptOverride: '',
    footerTemplate: '\n\n---\nConverted on {{date}} using {{model}}',
    useSeparatePluginSettings: false,
};
