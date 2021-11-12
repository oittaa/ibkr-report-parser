function giveOnchangeEvent(input) {
  document.getElementById("file").onchange = function() {
    document.getElementById("form").submit();
  }
}
document.getElementById('file').addEventListener('click', giveOnchangeEvent)
