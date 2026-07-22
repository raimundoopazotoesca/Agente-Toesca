
const code = ` + json.dumps(content[:5000]) + `;
try {
    eval(code);
    console.log("OK");
} catch(e) {
    console.log("ERROR at line " + e.stack.split("
")[0]);
    console.log(e.message);
}
