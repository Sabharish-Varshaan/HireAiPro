# HireAiPro: the only runtimes installed in this image. Replaces Judge0's
# db/languages/active.rb so /languages lists exactly what can actually run.
# Names state the real installed versions; paths are the real binaries.
@languages ||= []
@languages +=
[
  {
    id: 71,
    name: "Python (3.8.1)",
    is_archived: false,
    source_file: "script.py",
    run_cmd: "/usr/local/python-3.8.1/bin/python3 script.py"
  },
  {
    id: 102,
    name: "JavaScript (Node.js 22.23.3)",
    is_archived: false,
    source_file: "script.js",
    run_cmd: "/usr/local/node-22/bin/node script.js"
  },
  {
    id: 105,
    name: "C++17 (GCC 12.2.0)",
    is_archived: false,
    source_file: "main.cpp",
    compile_cmd: "/usr/bin/g++ -std=c++17 -O2 -pipe %s main.cpp",
    run_cmd: "./a.out"
  },
]
