# -*- coding: utf-8 -*-
"""
MÓDULO DE GERENCIAMENTO GEOMÉTRICO DE BUFFERS E SENSORES INDIVIDUAIS
Compatível com config.json (idêntico ao Controle_Velocidade_4).
Modela cada sensor discreto com posição física, área e status real/virtual.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any


@dataclass
class SetorEsteira:
    ordem: int
    tag: str
    comprimento_m: float
    largura_m: float
    contato_ativo: bool = False   # Valor lido no OPC que indica presença de garrafa (ex: False para sensor óptico que corta sinal)
    habilitado: bool = True
    descricao: str = ""
    valor_lido: Optional[bool] = None  # Último valor lido da tag OPC UA física
    ocupado_virtual: bool = False       # Estado simulado pelo Gêmeo Digital Contrafactual

    @property
    def area_m2(self) -> float:
        """Área física do setor em metros quadrados."""
        return round(float(self.comprimento_m) * float(self.largura_m), 4)

    @property
    def ocupado_real(self) -> bool:
        """Verifica se o setor físico está ocupado no CLP real."""
        if not self.habilitado or self.valor_lido is None:
            return False
        return bool(self.valor_lido) == bool(self.contato_ativo)

    @property
    def ocupado(self) -> bool:
        """Alias para ocupado_real (retrocompatibilidade)."""
        return self.ocupado_real


class BufferGeometrico:
    def __init__(self, id_buffer: str, nome: str = "", capacidade_area_total_m2: Optional[float] = None):
        self.id_buffer = id_buffer.lower()  # "b1", "b2", "b3", "b4"
        self.nome = nome or f"Buffer {id_buffer.upper()}"
        self.capacidade_area_total_m2 = capacidade_area_total_m2
        self.setores: List[SetorEsteira] = []

    def adicionar_setor(self, setor: SetorEsteira):
        self.setores.append(setor)
        self.setores.sort(key=lambda s: s.ordem)

    @property
    def area_total_habilitada_m2(self) -> float:
        """Soma das áreas de todos os setores habilitados."""
        if self.capacidade_area_total_m2 is not None and self.capacidade_area_total_m2 > 0:
            return float(self.capacidade_area_total_m2)
        area_soma = sum(s.area_m2 for s in self.setores if s.habilitado)
        return round(area_soma, 4)

    def obter_area_incremental_pct(self, setor: SetorEsteira) -> float:
        """Calcula o percentual que este setor representa em relação à área total do buffer."""
        if not setor.habilitado:
            return 0.0
        total = self.area_total_habilitada_m2
        if total <= 0:
            return 0.0
        return round((setor.area_m2 / total) * 100.0, 2)

    def atualizar_sensor(self, tag: str, valor: Any) -> bool:
        """Atualiza o valor lido de um sensor pertencente a este buffer."""
        encontrado = False
        val_bool = bool(valor) if valor is not None else None
        tag_limpa = tag.strip()
        for setor in self.setores:
            if setor.tag.strip() == tag_limpa:
                setor.valor_lido = val_bool
                encontrado = True
        return encontrado

    def calcular_nivel_real_pct(self) -> float:
        """Calcula o nível físico real acumulado de garrafas no buffer [0.0% a 100.0%]."""
        if not self.setores:
            return 50.0

        total_area = self.area_total_habilitada_m2
        if total_area <= 0:
            return 0.0

        area_ocupada = sum(s.area_m2 for s in self.setores if s.habilitado and s.ocupado_real)
        nivel_pct = (area_ocupada / total_area) * 100.0
        return round(max(0.0, min(100.0, nivel_pct)), 2)

    def calcular_nivel_pct(self) -> float:
        """Alias para calcular_nivel_real_pct."""
        return self.calcular_nivel_real_pct()

    def propagar_nivel_virtual_nos_setores(self, nivel_virtual_pct: float, direcao_acumulo: str = "jusante_para_montante"):
        """
        Propaga o nível virtual do buffer sobre CADA SENSOR individual.
        Determina exatamente quais sensores físicos estariam cobertos ou livres sob o controle legado.
        
        - 'jusante_para_montante' (ex: B3): garrafas acumulam do final da esteira em direção à enchedora.
        - 'montante_para_jusante' (ex: B2): garrafas abastecem a partir da DPL até a enchedora.
        """
        if not self.setores:
            return

        total_area = self.area_total_habilitada_m2
        if total_area <= 0:
            return

        area_alvo_ocupada = (nivel_virtual_pct / 100.0) * total_area
        setores_ordenados = list(self.setores)
        if direcao_acumulo == "jusante_para_montante":
            setores_ordenados.reverse()

        area_acumulada = 0.0
        for setor in setores_ordenados:
            if not setor.habilitado:
                setor.ocupado_virtual = False
                continue

            area_acumulada += setor.area_m2
            # Se a área ocupada virtual atinge o setor, ele é considerado ocupado
            setor.ocupado_virtual = bool(area_acumulada <= (area_alvo_ocupada + (setor.area_m2 * 0.5)))

    def obter_sensor_por_ordem(self, ordem: int) -> Optional[SetorEsteira]:
        for s in self.setores:
            if s.ordem == ordem:
                return s
        return None

    def obter_sensor_por_tag(self, tag: str) -> Optional[SetorEsteira]:
        tag_limpa = tag.strip()
        for s in self.setores:
            if s.tag.strip() == tag_limpa:
                return s
        return None

    def obter_sensor_extremo_encher(self) -> Optional[SetorEsteira]:
        """Retorna o setor mais próximo da enchedora."""
        if not self.setores:
            return None
        # Para B3, setor de menor ordem (ordem 1) fica na descarga da enchedora
        # Para B2, setor de maior ordem (última ordem) fica na entrada da enchedora
        if self.id_buffer == "b3":
            return self.setores[0]
        elif self.id_buffer == "b2":
            return self.setores[-1]
        return self.setores[0]

    def obter_tabela_resumo(self) -> List[Dict[str, Any]]:
        """Gera relatório de todos os setores e sensores."""
        linhas = []
        for s in self.setores:
            linhas.append({
                "ordem": s.ordem,
                "tag": s.tag,
                "comprimento_m": s.comprimento_m,
                "largura_m": s.largura_m,
                "area_m2": s.area_m2,
                "area_incremental_pct": self.obter_area_incremental_pct(s),
                "contato_ativo": s.contato_ativo,
                "habilitado": s.habilitado,
                "valor_lido": s.valor_lido,
                "ocupado_real": s.ocupado_real,
                "ocupado_virtual": s.ocupado_virtual,
                "descricao": s.descricao
            })
        return linhas


class GerenciadorBuffers:
    """Gerencia a coleção de buffers e sensores B1, B2, B3 e B4 a partir do config.json."""

    def __init__(self):
        self.buffers: Dict[str, BufferGeometrico] = {
            "b1": BufferGeometrico("b1", "B1 - Extremo Entrada (Montante)"),
            "b2": BufferGeometrico("b2", "B2 - Entrada Imediata (Alimentação Enchedora)"),
            "b3": BufferGeometrico("b3", "B3 - Saída Imediata (Saída Enchedora para Pasteurizador)"),
            "b4": BufferGeometrico("b4", "B4 - Extremo Saída (Jusante / Pós-Pasteurizador)")
        }
        self.mapa_tags: Dict[str, List[BufferGeometrico]] = {}

    def configurar_a_partir_do_dict(self, config_dict: Dict[str, Any]):
        """Carrega a definição exata dos buffers e setores do config.json (idêntico ao V4)."""
        buffers_cfg = config_dict.get("buffers", {})
        for buf_id in ["b1", "b2", "b3", "b4"]:
            cfg_b = buffers_cfg.get(buf_id.upper(), buffers_cfg.get(buf_id, {}))
            if not isinstance(cfg_b, dict):
                continue
            
            nome = cfg_b.get("nome", f"Buffer {buf_id.upper()}")
            cap_m2 = cfg_b.get("capacidade_area_total_m2", None)
            buf = BufferGeometrico(buf_id, nome=nome, capacidade_area_total_m2=cap_m2)

            setores_lista = cfg_b.get("setores", [])
            for item in setores_lista:
                setor = SetorEsteira(
                    ordem=int(item.get("ordem", 1)),
                    tag=str(item.get("tag", "")).strip(),
                    comprimento_m=float(item.get("comprimento_m", 0.0)),
                    largura_m=float(item.get("largura_m", 0.0)),
                    contato_ativo=bool(item.get("contato_ativo", False)),
                    habilitado=bool(item.get("habilitado", True)),
                    descricao=str(item.get("descricao", ""))
                )
                buf.adicionar_setor(setor)

            self.buffers[buf_id] = buf

        self._reconstruir_mapa_tags()

    def _reconstruir_mapa_tags(self):
        self.mapa_tags.clear()
        for buf in self.buffers.values():
            for setor in buf.setores:
                tag = setor.tag.strip()
                if tag:
                    if tag not in self.mapa_tags:
                        self.mapa_tags[tag] = []
                    self.mapa_tags[tag].append(buf)

    def obter_todas_as_tags_sensores(self) -> List[str]:
        """Retorna lista única de todas as tags de sensores configuradas nos buffers."""
        return list(self.mapa_tags.keys())

    def atualizar_valor_sensor(self, tag: str, valor: Any) -> bool:
        """Atualiza o valor lido de um sensor e reavalia a ocupação."""
        tag_limpa = str(tag).strip()
        buffers_associados = self.mapa_tags.get(tag_limpa, [])
        if not buffers_associados:
            return False
        atualizou = False
        for buf in buffers_associados:
            if buf.atualizar_sensor(tag_limpa, valor):
                atualizou = True
        return atualizou

    def calcular_todos_os_niveis_reais(self) -> Dict[str, float]:
        """Calcula os níveis percentuais reais agregados a partir dos sensores."""
        return {
            "b1": self.buffers["b1"].calcular_nivel_real_pct(),
            "b2": self.buffers["b2"].calcular_nivel_real_pct(),
            "b3": self.buffers["b3"].calcular_nivel_real_pct(),
            "b4": self.buffers["b4"].calcular_nivel_real_pct()
        }

    def propagar_niveis_virtuais(self, b2_virt_pct: float, b3_virt_pct: float):
        """Propaga os níveis contrafactuais sobre cada sensor individual de B2 e B3."""
        self.buffers["b2"].propagar_nivel_virtual_nos_setores(b2_virt_pct, direcao_acumulo="montante_para_jusante")
        self.buffers["b3"].propagar_nivel_virtual_nos_setores(b3_virt_pct, direcao_acumulo="jusante_para_montante")
