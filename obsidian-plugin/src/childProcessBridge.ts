import { execFile } from 'child_process';

export interface ConversionOptions {
    apiKey: string;
    modelName: string;
    promptOverride: string;
    generatorPriority: string[];
}

export class ChildProcessBridge {
    async convertFile(filePath: string, options: ConversionOptions, scriptPath: string): Promise<string> {
        return new Promise((resolve, reject) => {
            execFile(
                'python',
                [scriptPath, filePath, JSON.stringify(options)],
                (error, stdout, stderr) => {
                    if (error) {
                        reject(`Error: ${error.message}`);
                        return;
                    }
                    if (stderr) {
                        console.warn(`Stderr: ${stderr}`);
                    }
                    resolve(stdout);
                },
            );
        });
    }
}
