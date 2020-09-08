var t = document.createElement('div')
t.setAttribute('class', 'tracker')
t.innerHTML = '0%'
document.body.appendChild(t)

function get_scroll() {
	var h = document.documentElement,
    	b = document.body,
        t = 'scrollTop',
        i = 'scrollHeight';

    var pc = (h[t] || b[t]) / ((h[i] || b[i]) - h.clientHeight)
    return Math.round(pc * 100, 2) + "%"
}

function track() {
	var tracker = document.getElementsByClassName('tracker')[0]
	tracker.innerHTML = get_scroll()
}
