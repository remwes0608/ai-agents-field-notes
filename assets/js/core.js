/* Copy button on every code block. Vendored from Hydrogen; its UI strings were Chinese. */
var codeblocks = document.getElementsByTagName("pre");
// one button per <pre>

for (var i = 0; i < codeblocks.length; i++) {
// create the button
currentCode = codeblocks[i];
currentCode.style = "position: relative;";
var copy = document.createElement("div");
copy.className = "copybtn ripple";
copy.innerHTML = "Copy";
currentCode.appendChild(copy);
// hidden until the block is hovered
copy.style.opacity = "0";
}

for (var i = 0; i < codeblocks.length; i++) {

!function (i) {
    // show on hover
    codeblocks[i].onmouseover = function () {
        codeblocks[i].childNodes[1].style.opacity='1'
    }

    // copy
    function copyArticle(event) {
        const range = document.createRange();

        // select the code, not the button we just added
        range.selectNode(codeblocks[i].childNodes[0]);

        const selection = window.getSelection();
        if (selection.rangeCount > 0) selection.removeAllRanges();
        selection.addRange(range);
        document.execCommand('copy');
        codeblocks[i].childNodes[1].style.color = "transparent";
        setTimeout(function () { codeblocks[i].childNodes[1].style.color = ""; }, 300);
        codeblocks[i].childNodes[1].style.width = "72px";
        setTimeout(function () { codeblocks[i].childNodes[1].innerHTML = "Copied"; }, 300);
        setTimeout(function () {
            codeblocks[i].childNodes[1].style.color = "transparent";
            setTimeout(function () { codeblocks[i].childNodes[1].style.color = ""; }, 300);
            codeblocks[i].childNodes[1].innerHTML = "Copy";
            codeblocks[i].childNodes[1].style.width = "46px";
        }, 1000);
        // drop the selection
        if (selection.rangeCount > 0) selection.removeAllRanges(); 0
    }
    codeblocks[i].childNodes[1].addEventListener('click', copyArticle, false);

}(i);

!function (i) {
    // hide again when the pointer leaves
    codeblocks[i].onmouseout = function () {
        codeblocks[i].childNodes[1].style.opacity='0'
    }
}(i);
}

/* Hydrogen's menu code lived here: it drove a `#fold` element with inline heights. The nav in
   this site is a CSS-only disclosure, so the script that reached for that element — and threw on
   every page that did not have it — is gone. */
