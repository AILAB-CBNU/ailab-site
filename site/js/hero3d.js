/* A deterministic, locally rendered 3D learning manifold. No CDN or WebGL required. */
(function () {
  'use strict';
  var host = document.querySelector('.hero-canvas');
  if (!host) return;
  var canvas = document.createElement('canvas'), ctx = canvas.getContext('2d');
  if (!ctx) return;
  host.appendChild(canvas);
  var motion = matchMedia('(prefers-reduced-motion: reduce)');
  var width = 1, height = 1, visible = true, raf = 0, last = 0, time = 0;
  var pointer = {x:0,y:0}, rotation = {x:0,y:0};
  var tau = Math.PI * 2, strands = [], count = 64, steps = 160;
  // A woven toroidal manifold: each continuous strand carries a data signal.
  for (var j=0;j<count;j++) {
    var v=j/count*tau, line=[];
    for (var i=0;i<=steps;i++) {
      var u=i/steps*tau, twist=v+u*1.5;
      var r=1.72+0.58*Math.cos(twist);
      line.push([r*Math.cos(u),r*Math.sin(u),0.66*Math.sin(twist)]);
    }
    strands.push(line);
  }
  function project(p) {
    var ax=0.88+rotation.y, ay=-0.35+rotation.x+Math.sin(time*0.12)*0.13;
    var y=p[1]*Math.cos(ax)-p[2]*Math.sin(ax), z=p[1]*Math.sin(ax)+p[2]*Math.cos(ax);
    var x=p[0]*Math.cos(ay)+z*Math.sin(ay); z=-p[0]*Math.sin(ay)+z*Math.cos(ay);
    var tilt=-0.2, xx=x*Math.cos(tilt)-y*Math.sin(tilt), yy=x*Math.sin(tilt)+y*Math.cos(tilt);
    var scale=Math.min(width/5.7,height/4.6), perspective=7.5/(7.5-z);
    return [width/2+xx*scale*perspective,height*0.49+yy*scale*perspective,z];
  }
  function draw() {
    ctx.clearRect(0,0,width,height);
    var glow=ctx.createRadialGradient(width/2,height*.85,0,width/2,height*.85,width*.32);
    glow.addColorStop(0,'rgba(76,122,176,0.09)'); glow.addColorStop(1,'rgba(76,122,176,0)');
    ctx.save();ctx.translate(0,height*.65);ctx.scale(1,.24);ctx.fillStyle=glow;ctx.fillRect(0,0,width,height*2);ctx.restore();
    var lines=strands.map(function(line,j){var pts=line.map(project);return {pts:pts,j:j,z:pts.reduce(function(s,p){return s+p[2];},0)/pts.length};}).sort(function(a,b){return a.z-b.z;});
    lines.forEach(function(line){
      var pts=line.pts;
      for(var i=0;i<steps;i++) {
        var a=pts[i],b=pts[i+1],depth=(a[2]+2.5)/5;
        var hue=211+25*Math.sin(i/steps*tau+line.j/count*1.2)-22*Math.cos(line.j/count*tau);
        ctx.strokeStyle='hsla('+hue+',68%,'+(36+depth*15)+'%,'+(0.16+depth*.43)+')';
        ctx.lineWidth=.65+depth*.4;ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke();
      }
      if(line.j%8===0){
        var index=Math.floor(((time*.032+line.j/count)%1)*steps),p=pts[index];
        ctx.fillStyle='rgba(21,94,172,.8)';ctx.beginPath();ctx.arc(p[0],p[1],1.7,0,tau);ctx.fill();
        ctx.fillStyle='rgba(73,153,215,.13)';ctx.beginPath();ctx.arc(p[0],p[1],5,0,tau);ctx.fill();
      }
    });
  }
  function frame(now) {
    raf=0;if(!visible||document.hidden||motion.matches)return;
    if(now-last>=1000/30){var dt=Math.min((now-last)/1000,.06);time+=dt;last=now;
      rotation.x+=(pointer.x-rotation.x)*.06;rotation.y+=(pointer.y-rotation.y)*.06;draw();}
    raf=requestAnimationFrame(frame);
  }
  function start(){if(!raf&&visible&&!document.hidden&&!motion.matches){last=performance.now();raf=requestAnimationFrame(frame);}}
  function resize(){width=host.clientWidth;height=host.clientHeight;var dpr=Math.min(devicePixelRatio||1,1.75);canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);draw();}
  host.addEventListener('pointermove',function(e){if(motion.matches||e.pointerType==='touch')return;var r=host.getBoundingClientRect();pointer.x=((e.clientX-r.left)/width-.5)*.2;pointer.y=((e.clientY-r.top)/height-.5)*.15;});
  host.addEventListener('pointerleave',function(){pointer.x=pointer.y=0;});
  new ResizeObserver(resize).observe(host);
  new IntersectionObserver(function(entries){visible=entries[0].isIntersecting;if(!visible&&raf){cancelAnimationFrame(raf);raf=0;}start();},{threshold:.01}).observe(host);
  document.addEventListener('visibilitychange',function(){if(document.hidden){cancelAnimationFrame(raf);raf=0;}else start();});
  motion.addEventListener('change',function(){cancelAnimationFrame(raf);raf=0;if(motion.matches){time=0;rotation.x=rotation.y=0;draw();}else start();});
  resize();start();
})();
