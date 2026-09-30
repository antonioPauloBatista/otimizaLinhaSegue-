# -*- coding: utf-8 -*-
"""
MÓDULO DE GERENCIAMENTO GEOMÉTRICO DE BUFFERS (ESTEIRAS)
Calcula a taxa de acúmulo (%) de cada buffer (B1, B2, B3, B4) a partir dos setores físicos
de esteira monitorados por sensores discretos via OPC UA.

Cada setor possui:
- Comprimento (metros)
- Largura (metros)
- Área = Comprimento * Largura (m²)
- Área incremental (%) = (Área do setor / Área total habilitada) * 100%
- Contato de sinal (True ou False, indicando qual valor lógico do sensor representa garrafa presente)
- Habilitado (True ou False)

Quando o sensor detecta presença de garrafa, sua área incremental é somada ao nível do buffer.
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
    valor_lido: Optional[bool] = None  # Último valor lido da tag OPC UA

    @property
    def area_m2(self) -> float:
        """Área física do setor em metros quadrados."""
        return round(float(self.comprimento_m) * float(self.largura_m), 4)

    @property
    def ocupado(self) -> bool:
        """Verifica se o setor está com garrafas acumuladas conforme o tipo de contato configurado."""
        if not self.habilitado or self.valor_lido is None:
            return False
        # Compara valor booleano ou int (0/1) com o contato_ativo esperado
        return bool(self.valor_lido) == bool(self.contato_ativo)


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
        for setor in self.setores:
            if setor.tag.strip() == tag.strip():
                setor.valor_lido = val_bool
                encontrado = True
        return encontrado

    def calcular_nivel_pct(self) -> float:
        """
        Calcula o nível total acumulado de garrafas no buffer [0.0% a 100.0%].
        Soma as áreas incrementais de todos os setores habilitados que estão ocupados.
        """
        if not self.setores:
            return 50.0  # Nível neutro seguro caso não haja setores configurados

        total_area = self.area_total_habilitada_m2
        if total_area <= 0:
            return 0.0

        area_ocupada = sum(s.area_m2 for s in self.setores if s.habilitado and s.ocupado)
        nivel_pct = (area_ocupada / total_area) * 100.0
        return round(max(0.0, min(100.0, nivel_pct)), 2)

    def obter_tabela_resumo(self) -> List[Dict[str, Any]]:
        """Gera relatório de todos os setores, similar à interface de monitoramento."""
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
                "ocupado": s.ocupado,
                "descricao": s.descricao
            })
        return linhas


class GerenciadorBuffers:
    """Gerencia a coleção de buffers B1, B2, B3 e B4."""

    def __init__(self):
        self.buffers: Dict[str, BufferGeometrico] = {
            "b1": BufferGeometrico("b1", "B1 - Extremo Entrada (Montante)"),
            "b2": BufferGeometrico("b2", "B2 - Entrada Imediata (Alimentação Enchedora)"),
            "b3": BufferGeometrico("b3", "B3 - Saída Imediata (Saída Enchedora para Pasteurizador)"),
            "b4": BufferGeometrico("b4", "B4 - Extremo Saída (Jusante / Pós-Pasteurizador)")
        }
        # Mapeamento reverso para busca instantânea de tags O(1)
        self.mapa_tags: Dict[str, List[BufferGeometrico]] = {}

    def configurar_a_partir_do_dict(self, config_dict: Dict[str, Any]):
        """Carrega a definição dos buffers a partir do dicionário de configuração."""
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

        # Reconstrói mapa de tags
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
        """Recebe notificação de mudança de valor de uma tag OPC UA e atualiza os setores correspondentes."""
        tag_limpa = str(tag).strip()
        buffers_associados = self.mapa_tags.get(tag_limpa, [])
        if not buffers_associados:
            return False
        atualizou = False
        for buf in buffers_associados:
            if buf.atualizar_sensor(tag_limpa, valor):
                atualizou = True
        return atualizou

    def calcular_todos_os_niveis(self) -> Dict[str, float]:
        """Retorna os níveis atuais percentuais calculados para b1, b2, b3 e b4."""
        return {
            "b1": self.buffers["b1"].calcular_nivel_pct(),
            "b2": self.buffers["b2"].calcular_nivel_pct(),
            "b3": self.buffers["b3"].calcular_nivel_pct(),
            "b4": self.buffers["b4"].calcular_nivel_pct()
        }
