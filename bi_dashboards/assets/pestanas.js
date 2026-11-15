document.addEventListener("keydown", (evento) => {
    const actual = evento.target.closest?.('#objetivos [role="tab"]');
    if (!actual || evento.altKey || evento.ctrlKey || evento.metaKey) return;

    const pestanas = Array.from(actual.parentElement.querySelectorAll('[role="tab"]'));
    const indice = pestanas.indexOf(actual);
    const destinos = {
        ArrowLeft: (indice + pestanas.length - 1) % pestanas.length,
        ArrowRight: (indice + 1) % pestanas.length,
        Home: 0,
        End: pestanas.length - 1,
    };
    if (!Object.hasOwn(destinos, evento.key)) return;

    evento.preventDefault();
    pestanas[destinos[evento.key]].focus();
});
