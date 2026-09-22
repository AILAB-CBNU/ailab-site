/* Locally drawn 3D field: a luminous sphere of interconnected learning trajectories. */
(function () {
  'use strict';
  var hero = document.querySelector('.hero'), host = document.querySelector('.hero-canvas');
  if (!hero || !host) return;
  var canvas = document.createElement('canvas'), ctx = canvas.getContext('2d');
  if (!ctx) return;
  host.appendChild(canvas);
  var content = hero.querySelector('.hero-content'), cue = hero.querySelector('.hero-bottom');
  var motion = matchMedia('(prefers-reduced-motion: reduce)');
  var w=1,h=1,raf=0,last=0,time=0,visible=true,progress=0,target=0;
  var pointer={x:0,y:0},rotation={x:0,y:0}, tau=Math.PI*2;
  var lines=[],stars=[];
  for(var j=0;j<48;j++) {
    var path=[],latitude=(j/47-.5)*Math.PI*.96;
    for(var i=0;i<=128;i++) {
      var u=i/128*tau, wave=latitude+.11*Math.sin(u*3+latitude*2);
      path.push([Math.cos(wave)*Math.cos(u),Math.sin(wave),Math.cos(wave)*Math.sin(u)]);
    }
    lines.push(path);
  }
  for(var n=0;n<90;n++)stars.push([(Math.sin(n*127.1)*43758.5453)%1,(Math.sin(n*311.7)*15427.3)%1,n%3]);
  function project(p) {
    var ax=-.28+rotation.y, ay=time*.075+rotation.x;
    var x=p[0]*Math.cos(ay)+p[2]*Math.sin(ay), z=-p[0]*Math.sin(ay)+p[2]*Math.cos(ay);
    var y=p[1]*Math.cos(ax)-z*Math.sin(ax);z=p[1]*Math.sin(ax)+z*Math.cos(ax);
    var tilt=-.23, xx=x*Math.cos(tilt)-y*Math.sin(tilt), yy=x*Math.sin(tilt)+y*Math.cos(tilt);
    var radius=Math.min(w*.37,h*.39)*(1+progress*1.4),perspective=4.8/(4.8-z);
    return [w*.5+xx*radius*perspective,h*(.76-progress*.12)+yy*radius*perspective,z];
  }
  function draw() {
    ctx.clearRect(0,0,w,h);
    var radius=Math.min(w*.48,h*.59)*(1+progress),cy=h*(.76-progress*.12);
    var glow=ctx.createRadialGradient(w*.5,cy,0,w*.5,cy,radius);
    glow.addColorStop(0,'rgba(28,81,147,.12)');glow.addColorStop(.65,'rgba(53,118,194,.12)');glow.addColorStop(1,'rgba(44,102,191,0)');
    ctx.fillStyle=glow;ctx.fillRect(0,0,w,h);
    stars.forEach(function(s){ctx.fillStyle='rgba(175,210,255,'+(s[2]*.06+.08)+')';ctx.fillRect(Math.abs(s[0])*w,Math.abs(s[1])*h,1,1);});
    var paths=lines.map(function(line,j){var points=line.map(project);return {points:points,j:j,z:points.reduce(function(a,p){return a+p[2];},0)/points.length};});
    paths.sort(function(a,b){return a.z-b.z;});
    paths.forEach(function(line) {
      var pts=line.points;
      for(var i=0;i<128;i++) {
        var a=pts[i],b=pts[i+1],depth=(a[2]+1)/2;
        ctx.strokeStyle='hsla('+(197+line.j*.7)+',80%,'+(52+depth*31)+'%,'+(.06+depth*.57)+')';
        ctx.lineWidth=.45+depth*.55;ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke();
        if(i%8===0&&line.j%2===0) {
          ctx.fillStyle='rgba(183,224,255,'+(.08+depth*.55)+')';ctx.beginPath();ctx.arc(a[0],a[1],.6+depth*.7,0,tau);ctx.fill();
        }
      }
      if(line.j%6===0) {
        var index=Math.floor((time*.018+line.j/48)%1*128),p=pts[index];
        ctx.fillStyle='rgba(111,188,255,.12)';ctx.beginPath();ctx.arc(p[0],p[1],7,0,tau);ctx.fill();
        ctx.fillStyle='#d5efff';ctx.beginPath();ctx.arc(p[0],p[1],1.7,0,tau);ctx.fill();
      }
    });
    if(!motion.matches) {
      content.style.transform='translateY('+(-progress*80)+'px)';
      content.style.opacity=String(1-progress*.82);
      cue.style.opacity=String(1-progress);
    }
  }
  function scroll() {
    target=motion.matches?0:Math.max(0,Math.min(1,-hero.getBoundingClientRect().top/Math.max(1,hero.offsetHeight-innerHeight)));
  }
  function frame(now) {
    raf=0;if(!visible||document.hidden||motion.matches)return;
    if(now-last>=1000/30) {
      time+=Math.min((now-last)/1000,.08);last=now;
      progress+=(target-progress)*.12;rotation.x+=(pointer.x-rotation.x)*.06;rotation.y+=(pointer.y-rotation.y)*.06;draw();
    }
    raf=requestAnimationFrame(frame);
  }
  function start(){if(!raf&&visible&&!document.hidden&&!motion.matches){last=performance.now();raf=requestAnimationFrame(frame);}}
  function resize(){w=host.clientWidth;h=host.clientHeight;var dpr=Math.min(devicePixelRatio||1,1.5);canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);scroll();draw();}
  hero.addEventListener('pointermove',function(e){if(motion.matches||e.pointerType==='touch')return;pointer.x=(e.clientX/w-.5)*.3;pointer.y=(e.clientY/h-.5)*.15;});
  hero.addEventListener('pointerleave',function(){pointer.x=pointer.y=0;});
  window.addEventListener('scroll',scroll,{passive:true});
  new ResizeObserver(resize).observe(host);
  new IntersectionObserver(function(entries){visible=entries[0].isIntersecting;if(!visible&&raf){cancelAnimationFrame(raf);raf=0;}start();}).observe(hero);
  document.addEventListener('visibilitychange',function(){if(document.hidden){cancelAnimationFrame(raf);raf=0;}else start();});
  motion.addEventListener('change',function(){cancelAnimationFrame(raf);raf=0;time=progress=target=0;content.style.transform='';content.style.opacity='';cue.style.opacity='';resize();start();});
  resize();start();
})();
