// Exporta los beneficios del Banco de Chile a bchile-importado.json
// 1) Abre https://sitiospublicos.bancochile.cl/personas/beneficios en Chrome o Edge.
// 2) Presiona F12, entra a la pestaña "Console" (Consola).
// 3) Pega todo este texto y presiona Enter. Se descarga el archivo.
(async () => {
  let todo = [], p = 1, total = 1;
  do {
    const r = await fetch('/api/content/spaces/personas/types/beneficios/entries?per_page=100&page=' + p).then(r => r.json());
    todo = todo.concat(r.entries);
    total = r.meta.total_pages;
    p++;
  } while (p <= total);
  const limpiar = h => (h || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 1000);
  const salida = todo.map(e => ({
    meta: { name: e.meta.name, slug: e.meta.slug, tags: e.meta.tags, category: e.meta.category, unpublish_at: e.meta.unpublish_at },
    fields: { Titulo: e.fields.Titulo, 'Tipo Beneficio': e.fields['Tipo Beneficio'], Extracto: e.fields.Extracto,
              Vigencia: e.fields.Vigencia, Keywords: e.fields.Keywords, Descripcion: limpiar(e.fields.Descripcion).slice(0, 600),
              Sucursales: e.fields.Sucursales || '', 'Sitio web': e.fields['Sitio web'] || '',
              'Url Beneficio Externa': e.fields['Url Beneficio Externa'] || '',
              'Condiciones Comerciales': limpiar(e.fields['Condiciones Comerciales']) }
  }));
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify({ exportado: new Date().toISOString(), entries: salida })], { type: 'application/json' }));
  a.download = 'bchile-importado.json';
  a.click();
  console.log('Listo: ' + salida.length + ' beneficios exportados');
})();
