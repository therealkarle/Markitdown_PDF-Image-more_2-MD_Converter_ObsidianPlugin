export type OcrEngine = 'tesseract' | 'azure_ocr' | 'win_ocr';

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
    ocrPriority: ['tesseract', 'azure_ocr'],
    aiAutoDetect: false,
    aiImprove: false,
    geminiApiKey: '',
    azureOcrKey: '',
    azureOcrEndpoint: '',
    tesseractLang: 'deu+eng',
    tesseractCmd: '',
    modelName: 'gemini-2.0-flash-lite-preview-02-05',
    promptOverride: '',
    footerTemplate: '\n\n---\nConverted on {{date}} using {{model}}',
    useSeparatePluginSettings: false,
};
