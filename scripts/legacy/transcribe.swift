#!/usr/bin/env swift
import Speech
import Foundation

// macOS built-in speech recognizer — zero dependencies
// Usage: echo "audio.wav" | swift transcribe.swift
// Or:    ./transcribe.swift audio.wav [audio2.wav ...]

let semaphore = DispatchSemaphore(value: 0)
var texts: [String] = []

func recognize(file url: URL, index: Int, completion: @escaping (String?) -> Void) {
    let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "zh-Hans"))
            ?? SFSpeechRecognizer()!
    let request = SFSpeechURLRecognitionRequest(url: url)
    request.shouldReportPartialResults = false

    recognizer.recognitionTask(with: request) { result, error in
        if let error = error {
            fputs("[\(index)] error: \(error.localizedDescription)\n", stderr)
            completion(nil)
            return
        }
        if let result = result, result.isFinal {
            completion(result.bestTranscription.formattedString)
            return
        }
        if error != nil || result == nil {
            completion(nil)
        }
    }
}

let args = CommandLine.arguments.dropFirst()
var files: [URL] = []

if args.isEmpty {
    // Read file paths from stdin, one per line
    while let line = readLine() {
        let trimmed = line.trimmingCharacters(in: .whitespaces)
        if !trimmed.isEmpty {
            files.append(URL(fileURLWithPath: trimmed))
        }
    }
} else {
    files = args.map { URL(fileURLWithPath: $0) }
}

guard !files.isEmpty else {
    fputs("No audio files provided\n", stderr)
    exit(1)
}

let group = DispatchGroup()
var results: [String?] = Array(repeating: nil, count: files.count)

for (i, file) in files.enumerated() {
    group.enter()
    recognize(file: file, index: i) { text in
        results[i] = text
        group.leave()
    }
}

group.wait()

for (i, text) in results.enumerated() {
    if let t = text {
        print("\(i)\t\(files[i].path)\t\(t)")
    } else {
        fputs("Warning: no transcription for \(files[i].path)\n", stderr)
    }
}
