// Rebuild the public project seed from the preserved source records.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const root = path.resolve(__dirname, '..');
global.window = {};
require(path.join(root, 'site/js/data.js'));
const data = window.SITE_DATA;
const rows = data.projects.map(p => {
  const years = (p.period.match(/\b(?:19|20)\d{2}\b/g) || []).map(Number);
  const closed = /^\d{4}(?:\s*[-–]\s*\d{4})?$/.test(p.period);
  return {id:'legacy-' + crypto.createHash('sha256').update(p.period+JSON.stringify(p.title)).digest('hex').slice(0,16),
    revision:1, title:p.title, year:years[0] || 2021, period:p.period,
    status:closed ? 'completed' : 'unknown', funder:p.funder, description:{ko:'',en:''}, source:''};
});
data.researchSupport.forEach(p => rows.push({id:p.id.toLowerCase(), revision:1,title:p.title,
  year:Number(p.publicationYear.match(/\d{4}/g).pop()), period:'', status:'unknown', funder:p.agency,
  description:{ko:p.description.ko+' · '+p.grant+' (논문 게재 연도 기준)',en:p.description.en+' · '+p.grant+' (publication year)'},source:p.source}));
fs.mkdirSync(path.join(root,'site/data'),{recursive:true});
fs.writeFileSync(path.join(root,'site/data/projects.json'),JSON.stringify(rows,null,2)+'\n');
